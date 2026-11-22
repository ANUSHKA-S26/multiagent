const API_BASE = "http://127.0.0.1:8000";

// ============================================================
// GLOBAL STATE
// ============================================================

let selectedMode = "autonomous";
let taskId = null;

let eventSource = null;
let statusInterval = null;
let resultsInterval = null;
let connectionLost = false;

let currentCopilotReviewKey = null;


// ============================================================
// DOM ELEMENTS
// ============================================================

const $ = (id) => document.getElementById(id);

const welcomePage = $("welcomePage");
const dashboard = $("dashboard");
const getStartedBtn = $("getStartedBtn");

const generatorForm = $("generatorForm");
const courseName = $("courseName");
const modelName = $("modelName");

const catalogConfigGroup = $("catalogConfigGroup");
const copilotConfigGroup = $("copilotConfigGroup");

const generatePptx = $("generatePptx");
const generateBtn = $("generateBtn");

const progressSection = $("progressSection");
const progressFill = $("progressFill");
const progressPercent = $("progressPercent");
const currentStage = $("currentStage");

const logsSection = $("logsSection");
const logsContainer = $("logsContainer");

const resultsSection = $("resultsSection");
const chapterResults = $("chapterResults");

const completionSection = $("completionSection");
const generateAnotherBtn = $("generateAnotherBtn");

const copilotReviewSection = $("copilotReviewSection");
const copilotReviewTitle = $("copilotReviewTitle");
const copilotReviewMessage = $("copilotReviewMessage");
const copilotFeedbackBox = $("copilotFeedbackBox");
const copilotChapterFeedback = $("copilotChapterFeedback");
const requestChangesBtn = $("requestChangesBtn");
const approveChapterBtn = $("approveChapterBtn");

const modeCards = document.querySelectorAll(".modeCard");


// ============================================================
// BASIC HELPERS
// ============================================================

function show(element) {
    if (element) {
        element.classList.remove("hidden");
    }
}


function hide(element) {
    if (element) {
        element.classList.add("hidden");
    }
}


// ============================================================
// PROGRESS
// ============================================================

function setProgress(value, stage = "") {

    let progress = Number(value);

    if (!Number.isFinite(progress)) {
        progress = 0;
    }

    progress = Math.max(0, Math.min(100, progress));

    if (progressFill) {
        progressFill.style.width = `${progress}%`;
    }

    if (progressPercent) {
        progressPercent.textContent = `${Math.round(progress)}%`;
    }

    if (currentStage) {
        currentStage.textContent = stage || "";
    }
}


// ============================================================
// LOGS
// ============================================================

function appendLog(message) {

    if (!logsContainer) {
        return;
    }

    if (message === undefined || message === null) {
        return;
    }

    const text = String(message).trimEnd();

    if (!text) {
        return;
    }

    const line = document.createElement("div");

    line.textContent =
        `[${new Date().toLocaleTimeString()}] ${text}`;

    logsContainer.appendChild(line);

    logsContainer.scrollTop =
        logsContainer.scrollHeight;
}


// ============================================================
// CONNECTION CLEANUP
// ============================================================

function stopPolling() {

    if (statusInterval) {
        clearInterval(statusInterval);
        statusInterval = null;
    }

    if (resultsInterval) {
        clearInterval(resultsInterval);
        resultsInterval = null;
    }
}


function stopAllConnections() {

    stopPolling();

    if (eventSource) {
        eventSource.close();
        eventSource = null;
    }
}


// ============================================================
// RESET
// ============================================================

function resetOutput() {

    stopAllConnections();

    connectionLost = false;
    taskId = null;
    currentCopilotReviewKey = null;

    setProgress(0, "Waiting...");

    if (logsContainer) {
        logsContainer.innerHTML = "";
    }

    if (chapterResults) {
        chapterResults.innerHTML = "";
    }

    hide(completionSection);
    hide(copilotReviewSection);
    hide(copilotFeedbackBox);

    if (copilotChapterFeedback) {
        copilotChapterFeedback.value = "";
    }
}


// ============================================================
// API HELPERS
// ============================================================

async function readJson(response) {

    try {
        return await response.json();
    }
    catch {
        return {};
    }
}


function apiError(data, fallback) {

    if (typeof data?.detail === "string") {
        return data.detail;
    }

    if (typeof data?.error === "string") {
        return data.error;
    }

    if (typeof data?.message === "string") {
        return data.message;
    }

    return fallback;
}


// ============================================================
// WELCOME
// ============================================================

if (getStartedBtn) {

    getStartedBtn.addEventListener("click", () => {

        hide(welcomePage);
        show(dashboard);

        if (courseName) {
            courseName.focus();
        }
    });
}


// ============================================================
// MODE SELECTION
// ============================================================

modeCards.forEach((card) => {

    card.addEventListener("click", () => {

        modeCards.forEach((item) => {
            item.classList.remove("active");
        });

        card.classList.add("active");

        selectedMode =
            card.dataset.mode || "autonomous";

        hide(catalogConfigGroup);
        hide(copilotConfigGroup);

        if (selectedMode === "catalog") {
            show(catalogConfigGroup);
        }

        if (selectedMode === "copilot") {
            show(copilotConfigGroup);
        }
    });
});


// ============================================================
// CATALOG DATA
// ============================================================

function buildCatalogData() {

    return {

        course_structure:
            $("catalogCourseStructure")?.value.trim() || "",

        institutional_requirements:
            $("catalogInstitutionalRequirements")
                ?.value.trim() || "",

        teaching_constraints: {

            description:
                $("catalogTeachingConstraints")
                    ?.value.trim() || "",

            max_slide_count:
                Number(
                    $("catalogMaxSlides")?.value
                ) || 30
        },

        student_profile:
            $("catalogStudentProfile")
                ?.value.trim() || "",

        prior_feedback:
            $("catalogPriorFeedback")
                ?.value.trim() || "",

        instructor_preferences:
            $("catalogInstructorPreferences")
                ?.value.trim() || "",

        assessment_design:
            $("catalogAssessmentDesign")
                ?.value.trim() || ""
    };
}


// ============================================================
// COPILOT INITIAL PREFERENCES
// ============================================================

function buildCopilotData() {

    return {

        learning_objectives:
            $("copilotLearningObjectives")
                ?.value.trim() || "",

        syllabus:
            $("copilotSyllabus")
                ?.value.trim() || "",

        slides:
            $("copilotSlides")
                ?.value.trim() || "",

        script:
            $("copilotScript")
                ?.value.trim() || "",

        assessment:
            $("copilotAssessment")
                ?.value.trim() || "",

        overall:
            $("copilotOverall")
                ?.value.trim() || ""
    };
}


// ============================================================
// GENERATE COURSE
// ============================================================

if (generatorForm) {

    generatorForm.addEventListener(
        "submit",
        async (event) => {

            event.preventDefault();

            const name =
                courseName?.value.trim();


            if (!name) {

                alert(
                    "Please enter a course name."
                );

                if (courseName) {
                    courseName.focus();
                }

                return;
            }


            resetOutput();


            if (generateBtn) {
                generateBtn.disabled = true;
            }


            show(progressSection);
            show(logsSection);
            show(resultsSection);

            hide(completionSection);
            hide(copilotReviewSection);


            setProgress(
                1,
                "Connecting to backend..."
            );


            appendLog(
                "Starting course generation..."
            );


            // ------------------------------------------------
            // REQUEST BODY
            // ------------------------------------------------

            const requestBody = {

                course_name: name,

                model_name:
                    modelName?.value ||
                    "qwen3:4b",

                exp_name:
                    `exp_${Date.now()}`,

                copilot:
                    selectedMode === "copilot",

                catalog:
                    selectedMode === "catalog"
                        ? "web_catalog"
                        : null,

                catalog_data:
                    selectedMode === "catalog"
                        ? buildCatalogData()
                        : null,

                copilot_data:
                    selectedMode === "copilot"
                        ? buildCopilotData()
                        : null,

                generate_pptx:
                    Boolean(
                        generatePptx?.checked
                    )
            };


            appendLog(
                `Course: ${requestBody.course_name}`
            );

            appendLog(
                `Model: ${requestBody.model_name}`
            );

            appendLog(
                `Mode: ${selectedMode}`
            );


            // ------------------------------------------------
            // SEND TO BACKEND
            // ------------------------------------------------

            try {

                const response =
                    await fetch(
                        `${API_BASE}/api/course/generate`,
                        {
                            method: "POST",

                            headers: {
                                "Content-Type":
                                    "application/json"
                            },

                            body:
                                JSON.stringify(
                                    requestBody
                                )
                        }
                    );


                const data =
                    await readJson(response);


                if (!response.ok) {

                    throw new Error(
                        apiError(
                            data,
                            "Could not start generation."
                        )
                    );
                }


                taskId =
                    data.task_id;


                appendLog(
                    `Task created: ${taskId}`
                );


                setProgress(
                    2,
                    "Task created"
                );


                startLogStream();
                startStatusPolling();
                startResultsPolling();

            }
            catch (error) {

                console.error(
                    "Generation start error:",
                    error
                );

                setProgress(
                    0,
                    "Could not connect to backend"
                );

                appendLog(
                    `ERROR: ${error.message}`
                );

                if (generateBtn) {
                    generateBtn.disabled = false;
                }

                alert(error.message);
            }
        }
    );
}


// ============================================================
// LIVE LOG STREAM
// ============================================================

function startLogStream() {

    if (!taskId) {
        return;
    }


    if (eventSource) {
        eventSource.close();
        eventSource = null;
    }


    appendLog(
        "Connecting to live backend logs..."
    );


    eventSource =
        new EventSource(
            `${API_BASE}/api/course/logs/${taskId}/stream`
        );


    eventSource.onopen = () => {

        appendLog(
            "Live log stream connected."
        );
    };


    eventSource.onmessage = (event) => {

        try {

            const data =
                JSON.parse(event.data);


            if (data.type === "connected") {

                appendLog(
                    data.message ||
                    "Connected."
                );
            }


            else if (data.type === "log") {

                appendLog(
                    data.message
                );
            }


            else if (data.type === "error") {

                appendLog(
                    `ERROR: ${data.message}`
                );
            }


            else if (data.type === "complete") {

                appendLog(
                    `Log stream finished: ${data.status}`
                );

                if (eventSource) {
                    eventSource.close();
                    eventSource = null;
                }
            }

        }
        catch (error) {

            console.error(
                "Invalid live log message:",
                error
            );
        }
    };


    eventSource.onerror = () => {

        if (eventSource) {
            eventSource.close();
            eventSource = null;
        }
    };
}


// ============================================================
// COPILOT REVIEW PANEL
// ============================================================

function showCopilotReview(data) {

    if (
        selectedMode !== "copilot" ||
        !copilotReviewSection
    ) {
        return;
    }


    const number =
        data.copilot_chapter_number || "";

    const total =
        data.copilot_total_chapters || "";

    const title =
        data.copilot_chapter_title ||
        "Current chapter";

    const revision =
        data.copilot_revision_count || 0;


    const reviewKey =
        `${number}:${revision}:${title}`;


    /*
     * Status is checked repeatedly.
     * Do not recreate the panel every time,
     * otherwise the user's typing gets erased.
     */

    if (
        currentCopilotReviewKey === reviewKey &&
        !copilotReviewSection.classList.contains(
            "hidden"
        )
    ) {
        return;
    }


    currentCopilotReviewKey =
        reviewKey;


    show(copilotReviewSection);


    if (copilotReviewTitle) {

        copilotReviewTitle.textContent =
            `Chapter ${number}` +
            `${total ? ` of ${total}` : ""}` +
            `: ${title}`;
    }


    if (copilotReviewMessage) {

        copilotReviewMessage.textContent =
            "Review the generated slides, script and assessment. " +
            "If everything looks good, continue to the next chapter. " +
            "Otherwise tell Copilot what you want changed.";
    }


    hide(copilotFeedbackBox);


    if (copilotChapterFeedback) {
        copilotChapterFeedback.value = "";
    }


    if (approveChapterBtn) {

        approveChapterBtn.disabled = false;

        approveChapterBtn.textContent =
            "Looks Good — Continue";
    }


    if (requestChangesBtn) {

        requestChangesBtn.disabled = false;

        requestChangesBtn.textContent =
            "Request Changes";
    }


    copilotReviewSection.scrollIntoView({
        behavior: "smooth",
        block: "center"
    });
}


// ============================================================
// COPILOT BUTTON LOADING
// ============================================================

function setCopilotReviewBusy(busy) {

    if (approveChapterBtn) {
        approveChapterBtn.disabled = busy;
    }

    if (requestChangesBtn) {
        requestChangesBtn.disabled = busy;
    }

    if (copilotChapterFeedback) {
        copilotChapterFeedback.disabled = busy;
    }
}


// ============================================================
// SEND COPILOT FEEDBACK
// ============================================================

async function sendCopilotFeedback(
    action,
    feedback = ""
) {

    if (!taskId) {
        return;
    }


    feedback =
        String(feedback || "").trim();


    if (
        action === "revise" &&
        !feedback
    ) {

        alert(
            "Please describe the changes you want."
        );

        if (copilotChapterFeedback) {
            copilotChapterFeedback.focus();
        }

        return;
    }


    setCopilotReviewBusy(true);


    appendLog(
        action === "revise"
            ? "Sending chapter changes to Copilot..."
            : "Approving chapter and continuing..."
    );


    try {

        const response =
            await fetch(
                `${API_BASE}/api/course/copilot/${taskId}/feedback`,
                {
                    method: "POST",

                    headers: {
                        "Content-Type":
                            "application/json"
                    },

                    body: JSON.stringify({
                        action: action,
                        feedback: feedback
                    })
                }
            );


        const data =
            await readJson(response);


        if (!response.ok) {

            throw new Error(
                apiError(
                    data,
                    "Could not send Copilot feedback."
                )
            );
        }


        hide(copilotReviewSection);


        if (copilotChapterFeedback) {
            copilotChapterFeedback.value = "";
        }


        appendLog(
            data.message ||
            "Copilot feedback accepted."
        );

    }
    catch (error) {

        console.error(
            "Copilot feedback error:",
            error
        );

        appendLog(
            `ERROR: ${error.message}`
        );

        alert(error.message);

        setCopilotReviewBusy(false);
    }
}


// ============================================================
// REQUEST CHANGES BUTTON
// ============================================================

if (requestChangesBtn) {

    requestChangesBtn.addEventListener(
        "click",
        () => {

            /*
             * First click:
             * open feedback box.
             */

            if (
                copilotFeedbackBox?.classList.contains(
                    "hidden"
                )
            ) {

                show(copilotFeedbackBox);

                requestChangesBtn.textContent =
                    "Apply Changes";

                if (copilotChapterFeedback) {
                    copilotChapterFeedback.focus();
                }

                return;
            }


            /*
             * Second click:
             * send revision request.
             */

            sendCopilotFeedback(
                "revise",
                copilotChapterFeedback?.value || ""
            );
        }
    );
}


// ============================================================
// APPROVE CHAPTER BUTTON
// ============================================================

if (approveChapterBtn) {

    approveChapterBtn.addEventListener(
        "click",
        () => {

            sendCopilotFeedback(
                "approve"
            );
        }
    );
}


// ============================================================
// STATUS POLLING
// ============================================================

function startStatusPolling() {

    if (!taskId) {
        return;
    }


    if (statusInterval) {
        clearInterval(statusInterval);
    }


    fetchTaskStatus();


    statusInterval =
        setInterval(
            fetchTaskStatus,
            1500
        );
}


// ============================================================
// FETCH STATUS
// ============================================================

async function fetchTaskStatus() {

    if (!taskId) {
        return;
    }


    try {

        const response =
            await fetch(
                `${API_BASE}/api/course/status/${taskId}`,
                {
                    cache: "no-store"
                }
            );


        if (!response.ok) {

            const data =
                await readJson(response);

            throw new Error(
                apiError(
                    data,
                    `Status request failed (${response.status})`
                )
            );
        }


        connectionLost = false;


        const data =
            await response.json();


        // ----------------------------------------------------
        // PROGRESS
        // ----------------------------------------------------

        setProgress(
            data.progress ?? 0,

            data.current_stage ||
            data.status ||
            "Running"
        );


        // ----------------------------------------------------
        // COPILOT WAITING
        // ----------------------------------------------------

        if (
            data.status === "awaiting_review" &&
            data.copilot_waiting
        ) {

            showCopilotReview(data);

            setProgress(
                data.progress ?? 0,

                data.current_stage ||
                "Waiting for your Copilot review"
            );
        }


        // ----------------------------------------------------
        // COPILOT GENERATING AGAIN
        // ----------------------------------------------------

        else if (
            selectedMode === "copilot" &&
            data.status === "running"
        ) {

            hide(copilotReviewSection);
        }


        // ----------------------------------------------------
        // COMPLETED
        // ----------------------------------------------------

        if (
            data.status === "completed"
        ) {

            stopPolling();


            setProgress(
                100,
                "Completed"
            );


            hide(copilotReviewSection);

            currentCopilotReviewKey =
                null;


            await fetchResults();


            show(completionSection);


            if (generateBtn) {
                generateBtn.disabled = false;
            }


            appendLog(
                "Course generation completed successfully."
            );
        }


        // ----------------------------------------------------
        // FAILED
        // ----------------------------------------------------

        else if (
            data.status === "failed"
        ) {

            stopAllConnections();


            if (generateBtn) {
                generateBtn.disabled = false;
            }


            setProgress(
                data.progress ?? 0,
                "Generation failed"
            );


            const errorMessage =
                data.error ||
                "Generation failed.";


            appendLog(
                `ERROR: ${errorMessage}`
            );


            alert(
                errorMessage
            );
        }

    }
    catch (error) {

        console.error(
            "Status polling error:",
            error
        );


        /*
         * Prevent endless error messages
         * if backend disconnects.
         */

        if (!connectionLost) {

            connectionLost = true;


            appendLog(
                `Backend connection problem: ${error.message}`
            );


            let oldProgress = 0;


            if (progressPercent) {

                oldProgress =
                    Number(
                        progressPercent.textContent
                            .replace("%", "")
                    ) || 0;
            }


            setProgress(
                oldProgress,
                "Backend connection interrupted"
            );
        }


        stopPolling();


        if (eventSource) {

            eventSource.close();
            eventSource = null;
        }


        if (generateBtn) {
            generateBtn.disabled = false;
        }
    }
}


// ============================================================
// RESULTS POLLING
// ============================================================

function startResultsPolling() {

    if (!taskId) {
        return;
    }


    if (resultsInterval) {
        clearInterval(resultsInterval);
    }


    fetchResults();


    resultsInterval =
        setInterval(
            fetchResults,
            3000
        );
}


// ============================================================
// FETCH RESULTS
// ============================================================

async function fetchResults() {

    if (!taskId) {
        return;
    }


    try {

        const response =
            await fetch(
                `${API_BASE}/api/course/results/${taskId}/files`,
                {
                    cache: "no-store"
                }
            );


        if (!response.ok) {

            console.warn(
                "Results request returned:",
                response.status
            );

            return;
        }


        const data =
            await response.json();


        renderResults(
            Array.isArray(data.files)
                ? data.files
                : []
        );


        if (
            data.status === "completed" ||
            data.status === "failed"
        ) {

            if (resultsInterval) {

                clearInterval(
                    resultsInterval
                );

                resultsInterval = null;
            }
        }

    }
    catch (error) {

        console.error(
            "Results polling error:",
            error
        );
    }
}


// ============================================================
// RENDER RESULTS
// ============================================================

function renderResults(files) {

    if (!chapterResults) {
        return;
    }


    chapterResults.innerHTML = "";


    if (!files.length) {

        const message =
            document.createElement("p");


        message.textContent =
            "Generated files will appear here while the workflow runs.";


        chapterResults.appendChild(
            message
        );

        return;
    }


    const groups = {};


    files.forEach((file) => {

        const normalized =
            String(file.path || "")
                .replaceAll("\\", "/");


        const parts =
            normalized
                .split("/")
                .filter(Boolean);


        const group =
            parts.length > 1
                ? parts[0]
                : "Course Level Files";


        if (!groups[group]) {
            groups[group] = [];
        }


        groups[group].push({
            ...file,
            path: normalized
        });
    });


    Object.keys(groups)
        .sort(
            (a, b) =>
                a.localeCompare(
                    b,
                    undefined,
                    {
                        numeric: true
                    }
                )
        )
        .forEach((group) => {

            const card =
                document.createElement("div");


            card.className =
                "chapterCard";


            const title =
                document.createElement("h3");


            title.textContent =
                group.replaceAll(
                    "_",
                    " "
                );


            card.appendChild(
                title
            );


            const table =
                document.createElement("table");


            table.className =
                "resultTable";


            const thead =
                document.createElement("thead");


            thead.innerHTML = `
                <tr>
                    <th>File Name</th>
                    <th>Type</th>
                    <th>Size</th>
                    <th>Download</th>
                </tr>
            `;


            table.appendChild(
                thead
            );


            const tbody =
                document.createElement("tbody");


            groups[group]
                .sort(
                    (a, b) =>
                        String(a.name)
                            .localeCompare(
                                String(b.name),
                                undefined,
                                {
                                    numeric: true
                                }
                            )
                )
                .forEach((file) => {

                    const row =
                        document.createElement("tr");


                    const name =
                        document.createElement("td");


                    name.textContent =
                        file.name ||
                        "Unknown";


                    const type =
                        document.createElement("td");


                    type.textContent =
                        (
                            file.type ||
                            "file"
                        )
                            .replace(
                                ".",
                                ""
                            )
                            .toUpperCase();


                    const size =
                        document.createElement("td");


                    size.textContent =
                        formatFileSize(
                            file.size
                        );


                    const action =
                        document.createElement("td");


                    const button =
                        document.createElement("button");


                    button.className =
                        "downloadBtn";


                    button.textContent =
                        "Download";


                    button.addEventListener(
                        "click",
                        () => {

                            downloadFile(
                                file.path
                            );
                        }
                    );


                    action.appendChild(
                        button
                    );


                    row.append(
                        name,
                        type,
                        size,
                        action
                    );


                    tbody.appendChild(
                        row
                    );
                });


            table.appendChild(
                tbody
            );


            card.appendChild(
                table
            );


            chapterResults.appendChild(
                card
            );
        });
}


// ============================================================
// FILE SIZE
// ============================================================

function formatFileSize(bytes) {

    const value =
        Number(bytes);


    if (
        !Number.isFinite(value) ||
        value < 0
    ) {
        return "-";
    }


    if (value < 1024) {
        return `${value} B`;
    }


    if (value < 1024 * 1024) {

        return `${(
            value / 1024
        ).toFixed(1)} KB`;
    }


    return `${(
        value /
        (1024 * 1024)
    ).toFixed(1)} MB`;
}


// ============================================================
// DOWNLOAD GENERATED FILE
// ============================================================

function downloadFile(path) {

    if (
        !taskId ||
        !path
    ) {
        return;
    }


    /*
     * Encode individual path segments.
     * This keeps chapter folders working.
     */

    const encodedPath =
        String(path)
            .replaceAll(
                "\\",
                "/"
            )
            .split("/")
            .map(
                encodeURIComponent
            )
            .join("/");


    window.open(
        `${API_BASE}/api/course/results/${taskId}/download/${encodedPath}`,
        "_blank",
        "noopener"
    );
}


// ============================================================
// GENERATE ANOTHER COURSE
// ============================================================

if (generateAnotherBtn) {

    generateAnotherBtn.addEventListener(
        "click",
        () => {

            resetOutput();


            if (generatorForm) {
                generatorForm.reset();
            }


            selectedMode =
                "autonomous";


            modeCards.forEach(
                (card) => {

                    card.classList.toggle(
                        "active",
                        card.dataset.mode ===
                            "autonomous"
                    );
                }
            );


            hide(catalogConfigGroup);
            hide(copilotConfigGroup);

            hide(progressSection);
            hide(logsSection);
            hide(resultsSection);
            hide(completionSection);


            if (modelName) {

                modelName.value =
                    "qwen3:4b";
            }


            if (courseName) {
                courseName.focus();
            }
        }
    );
}


// ============================================================
// PAGE CLOSE CLEANUP
// ============================================================

window.addEventListener(
    "beforeunload",
    () => {

        stopAllConnections();
    }
);


// ============================================================
// INITIAL STATE
// ============================================================

if (modelName) {

    modelName.value =
        "qwen3:4b";
}


if (courseName) {
    courseName.focus();
}