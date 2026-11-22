"""
Local FastAPI backend for Instructional Agents.

This server:
- Uses the project's existing local Ollama/Qwen workflow
- Does NOT require an OpenAI API key
- Keeps FastAPI responsive while ADDIE is running
- Streams live logs to the frontend
- Reports real workflow progress
- Exposes generated files for download
"""
import os
import asyncio
import json
import re
import sys
import uuid
import threading

from datetime import datetime
from pathlib import Path
from queue import Empty, Queue
from typing import Any, Dict, Optional

import uvicorn

from fastapi import (
    BackgroundTasks,
    FastAPI,
    File,
    HTTPException,
    UploadFile,
)

from fastapi.middleware.cors import CORSMiddleware

from fastapi.responses import (
    FileResponse,
    StreamingResponse,
)

from pydantic import BaseModel, Field

from run import run_instructional_design
from src.ADDIE import ADDIE, ADDIERunner
from src import __version__


# ============================================================
# FASTAPI APP
# ============================================================

app = FastAPI(
    title="Instructional Agents API",
    description="Local Ollama-powered course generation API",
    version=__version__,
)


# ============================================================
# CORS
# ============================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5500",
        "http://localhost:5500",
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# IN-MEMORY TASK STORAGE
# ============================================================

tasks: Dict[str, Dict[str, Any]] = {}

task_logs: Dict[str, Queue] = {}

# Web-Copilot controls. Each interactive task has a thread-safe event
# used to pause chapter generation until the browser sends approve/revise.
copilot_controls: Dict[str, Dict[str, Any]] = {}


# ============================================================
# REQUEST MODEL
# ============================================================

class CourseRequest(BaseModel):

    course_name: str = Field(
        ...,
        min_length=1
    )

    model_name: str = Field(
        default="qwen3:4b"
    )

    exp_name: str = Field(
        default="default"
    )

    copilot: bool = False

    catalog: Optional[str] = None

    catalog_data: Optional[
        Dict[str, Any]
    ] = None

    copilot_data: Optional[
        Dict[str, Any]
    ] = None

    generate_pptx: bool = False


class CopilotFeedbackRequest(BaseModel):
    action: str = Field(..., description="approve or revise")
    feedback: str = Field(default="")


# ============================================================
# STATUS RESPONSE MODEL
# ============================================================

class TaskStatus(BaseModel):

    task_id: str

    status: str

    progress: int

    current_stage: Optional[str] = None

    error: Optional[str] = None

    created_at: str

    updated_at: str

    exp_name: Optional[str] = None

    copilot_waiting: bool = False

    copilot_chapter_number: Optional[int] = None

    copilot_total_chapters: Optional[int] = None

    copilot_chapter_title: Optional[str] = None

    copilot_revision_count: int = 0


# ============================================================
# TIME HELPER
# ============================================================

def now() -> str:

    return datetime.now().isoformat()


# ============================================================
# UPDATE TASK
# ============================================================

def update_task(
    task_id: str,
    **changes: Any
):

    if task_id not in tasks:
        return

    tasks[task_id].update(
        changes
    )

    tasks[task_id][
        "updated_at"
    ] = now()


# ============================================================
# ADD LIVE LOG
# ============================================================

def put_log(
    task_id: str,
    message: str
):

    if not message:
        return

    task_logs.setdefault(
        task_id,
        Queue()
    ).put(
        str(message)
    )


# ============================================================
# CONVERT ADDIE OUTPUT INTO PROGRESS
# ============================================================

def update_progress_from_log(
    task_id: str,
    line: str
):

    text = line.strip()

    if not text:
        return


    # ========================================================
    # FOUNDATION DELIBERATIONS
    #
    # Expected ADDIE output:
    #
    # Deliberation 1/6: Instructional Goals
    # Deliberation 2/6: Resource Assessment
    # ...
    # ========================================================

    match = re.search(
        r"Deliberation\s+(\d+)\s*/\s*(\d+)\s*:\s*(.+)",
        text,
        re.IGNORECASE
    )

    if match:

        current = int(
            match.group(1)
        )

        total = max(
            1,
            int(match.group(2))
        )

        name = (
            match.group(3)
            .strip()
        )


        # Foundation occupies approximately
        # 10% -> 58%

        progress = (
            10
            +
            int(
                (current - 1)
                / total
                * 48
            )
        )


        update_task(
            task_id,

            progress=min(
                progress,
                58
            ),

            current_stage=
                f"Foundation: {name}"
        )

        return


    # ========================================================
    # SYLLABUS PROCESSING
    # ========================================================

    if (
        "Syllabus processed into"
        in text
        or
        "Processed chapters saved"
        in text
    ):

        update_task(
            task_id,

            progress=62,

            current_stage=
                "Syllabus processed into chapters"
        )

        return


    # ========================================================
    # CHAPTER PHASE START
    # ========================================================

    if (
        "Starting ADDIE Workflow: Chapter Development Phase"
        in text
    ):

        update_task(
            task_id,

            progress=65,

            current_stage=
                "Starting chapter development"
        )

        return


    # ========================================================
    # CHAPTER PROGRESS
    #
    # Expected:
    #
    # Chapter 1/5: Introduction
    # Chapter 2/5: DFS Algorithm
    # ...
    # ========================================================

    match = re.search(
        r"^Chapter\s+(\d+)\s*/\s*(\d+)\s*:\s*(.+)",
        text,
        re.IGNORECASE
    )

    if match:

        current = int(
            match.group(1)
        )

        total = max(
            1,
            int(match.group(2))
        )

        title = (
            match.group(3)
            .strip()
        )


        # Chapter phase occupies
        # approximately 65% -> 94%

        progress = (
            65
            +
            int(
                (current - 1)
                / total
                * 29
            )
        )


        update_task(
            task_id,

            progress=min(
                progress,
                94
            ),

            current_stage=(
                f"Generating Chapter "
                f"{current}/{total}: "
                f"{title}"
            )
        )

        return


    # ========================================================
    # SLIDES / SCRIPT / ASSESSMENT
    # ========================================================

    match = re.search(
        r"Slides Generation for Chapter\s+(\d+).*?:\s*(.+)",
        text,
        re.IGNORECASE
    )

    if match:

        chapter_number = (
            match.group(1)
        )

        update_task(
            task_id,

            current_stage=(
                "Generating slides, script "
                "and assessment for "
                f"Chapter {chapter_number}"
            )
        )

        return


    # ========================================================
    # LATEX COMPILATION
    # ========================================================

    if (
        "Compiling LaTeX"
        in text
        or
        "compile_all"
        in text
    ):

        update_task(
            task_id,

            progress=95,

            current_stage=
                "Compiling generated course files"
        )

        return


    # ========================================================
    # PPTX
    # ========================================================

    if (
        "Generating PPTX"
        in text
    ):

        update_task(
            task_id,

            progress=97,

            current_stage=
                "Generating PowerPoint files"
        )

        return


# ============================================================
# STDOUT CAPTURE
#
# Captures ADDIE/Qwen print() output.
#
# The same output still appears in VS Code terminal AND gets
# streamed to frontend Live Logs.
# ============================================================

class LogCapture:

    def __init__(
        self,
        task_id: str,
        original_stdout
    ):

        self.task_id = task_id

        self.original_stdout = (
            original_stdout
        )

        self.buffer = ""

        self.workflow_error: Optional[
            str
        ] = None


    # --------------------------------------------------------
    # Process complete console line
    # --------------------------------------------------------

    def _handle_line(
        self,
        line: str
    ):

        clean = line.rstrip()

        if not clean:
            return


        # Send to frontend

        put_log(
            self.task_id,
            clean
        )


        # Update progress

        update_progress_from_log(
            self.task_id,
            clean
        )


        # ----------------------------------------------------
        # Detect ADDIE internal errors
        #
        # ADDIE may catch exceptions internally, which means
        # Python might otherwise return normally and the API
        # would incorrectly mark the task completed.
        # ----------------------------------------------------

        if clean.startswith(
            "Error running ADDIE workflow:"
        ):

            self.workflow_error = (
                clean.split(
                    ":",
                    1
                )[1].strip()
                or clean
            )


        elif (
            "No chapters found. Please ensure syllabus processing was successful."
            in clean
        ):

            self.workflow_error = (
                "No chapters were generated "
                "from the syllabus."
            )


    # --------------------------------------------------------
    # stdout.write()
    # --------------------------------------------------------

    def write(
        self,
        text
    ):

        # Keep terminal output visible

        try:

            self.original_stdout.write(
                text
            )

            self.original_stdout.flush()

        except Exception:

            pass


        if not text:
            return


        self.buffer += str(text)


        while "\n" in self.buffer:

            line, self.buffer = (
                self.buffer.split(
                    "\n",
                    1
                )
            )

            self._handle_line(
                line
            )


    # --------------------------------------------------------
    # stdout.flush()
    # --------------------------------------------------------

    def flush(self):

        if self.buffer.strip():

            self._handle_line(
                self.buffer
            )

            self.buffer = ""


        try:

            self.original_stdout.flush()

        except Exception:

            pass


    def isatty(self):

        return False


# ============================================================
# HEALTH CHECK
# ============================================================

@app.get("/health")
async def health_check():

    return {

        "status":
            "healthy",

        "mode":
            "local-ollama",

        "model_default":
            "qwen3:4b",

        "version":
            __version__,

        "timestamp":
            now()
    }


# ============================================================
# START COURSE GENERATION
# ============================================================

@app.post(
    "/api/course/generate"
)
async def generate_course(
    request: CourseRequest,
    background_tasks: BackgroundTasks
):

    # --------------------------------------------------------
    # COPILOT PROTECTION
    # --------------------------------------------------------

    


    # --------------------------------------------------------
    # CREATE TASK
    # --------------------------------------------------------

    task_id = str(
        uuid.uuid4()
    )


    tasks[task_id] = {

        "task_id":
            task_id,

        "status":
            "starting",

        "progress":
            1,

        "current_stage":
            "Task queued",

        "error":
            None,

        "created_at":
            now(),

        "updated_at":
            now(),

        "exp_name":
            request.exp_name,

        "course_name":
            request.course_name,

        "copilot_waiting":
            False,

        "copilot_chapter_number":
            None,

        "copilot_total_chapters":
            None,

        "copilot_chapter_title":
            None,

        "copilot_revision_count":
            0
    }

    if request.copilot:
        copilot_controls[task_id] = {
            "event": threading.Event(),
            "action": None,
            "feedback": "",
            "revision_count": 0,
        }


    task_logs[task_id] = (
        Queue()
    )


    # --------------------------------------------------------
    # START BACKGROUND WORK
    # --------------------------------------------------------

    background_tasks.add_task(

        run_generation_task,

        task_id,

        request
    )


    return {

        "task_id":
            task_id,

        "status":
            "started",

        "message":
            "Local course generation started"
    }


# ============================================================
# COPILOT REVIEW / FEEDBACK
# ============================================================

@app.post("/api/course/copilot/{task_id}/feedback")
async def submit_copilot_feedback(
    task_id: str,
    request: CopilotFeedbackRequest
):
    """
    Resume a paused Copilot chapter.

    action=approve  -> keep the chapter and generate the next one.
    action=revise   -> regenerate the current chapter using feedback.
    """
    if task_id not in tasks:
        raise HTTPException(status_code=404, detail="Task not found")

    if not tasks[task_id].get("copilot_waiting"):
        raise HTTPException(
            status_code=409,
            detail="This Copilot task is not waiting for chapter feedback."
        )

    action = request.action.strip().lower()

    if action not in {"approve", "revise"}:
        raise HTTPException(
            status_code=400,
            detail="action must be 'approve' or 'revise'"
        )

    feedback = request.feedback.strip()

    if action == "revise" and not feedback:
        raise HTTPException(
            status_code=400,
            detail="Please provide feedback when requesting changes."
        )

    control = copilot_controls.get(task_id)

    if not control:
        raise HTTPException(
            status_code=404,
            detail="Copilot control not found."
        )

    control["action"] = action
    control["feedback"] = feedback

    if action == "revise":
        control["revision_count"] += 1
        tasks[task_id]["copilot_revision_count"] = control["revision_count"]

    tasks[task_id]["copilot_waiting"] = False
    tasks[task_id]["status"] = "running"
    tasks[task_id]["current_stage"] = (
        "Applying your chapter feedback"
        if action == "revise"
        else "Chapter approved; continuing to next chapter"
    )

    put_log(
        task_id,
        "Copilot response received: "
        + ("revise chapter" if action == "revise" else "chapter approved")
    )

    control["event"].set()

    return {
        "success": True,
        "task_id": task_id,
        "action": action,
        "message": (
            "Feedback accepted. The current chapter will be revised."
            if action == "revise"
            else "Chapter approved. Continuing to the next chapter."
        )
    }


# ============================================================
# TASK STATUS
# ============================================================

@app.get(
    "/api/course/status/{task_id}",
    response_model=TaskStatus
)
async def get_task_status(
    task_id: str
):

    if task_id not in tasks:

        raise HTTPException(
            status_code=404,
            detail="Task not found"
        )


    return tasks[
        task_id
    ]


# ============================================================
# LIVE LOG STREAM
# ============================================================

@app.get(
    "/api/course/logs/{task_id}/stream"
)
async def stream_task_logs(
    task_id: str
):

    if task_id not in tasks:

        raise HTTPException(
            status_code=404,
            detail="Task not found"
        )


    async def event_generator():

        queue = task_logs.setdefault(
            task_id,
            Queue()
        )


        # Initial connection message

        connected = {

            "type":
                "connected",

            "message":
                "Connected to local generation logs"
        }


        yield (
            "data: "
            +
            json.dumps(
                connected
            )
            +
            "\n\n"
        )


        while True:

            sent_any = False


            # ------------------------------------------------
            # Drain available messages
            # ------------------------------------------------

            for _ in range(50):

                try:

                    message = (
                        queue.get_nowait()
                    )

                except Empty:

                    break


                sent_any = True


                payload = {

                    "type":
                        "log",

                    "message":
                        str(message),

                    "timestamp":
                        now()
                }


                yield (
                    "data: "
                    +
                    json.dumps(
                        payload,
                        ensure_ascii=False
                    )
                    +
                    "\n\n"
                )


            # ------------------------------------------------
            # Check task completion
            # ------------------------------------------------

            task = tasks.get(
                task_id
            )


            if (
                task
                and
                task["status"]
                in {
                    "completed",
                    "failed"
                }
                and
                queue.empty()
            ):

                payload = {

                    "type":
                        "complete",

                    "status":
                        task["status"]
                }


                yield (
                    "data: "
                    +
                    json.dumps(
                        payload
                    )
                    +
                    "\n\n"
                )


                break


            # ------------------------------------------------
            # SSE heartbeat
            # ------------------------------------------------

            if not sent_any:

                yield (
                    ": heartbeat\n\n"
                )

                await asyncio.sleep(
                    0.5
                )

            else:

                await asyncio.sleep(
                    0.01
                )


    return StreamingResponse(

        event_generator(),

        media_type=
            "text/event-stream",

        headers={

            "Cache-Control":
                "no-cache, no-transform",

            "Connection":
                "keep-alive",

            "X-Accel-Buffering":
                "no"
        }
    )


# ============================================================
# GENERATED FILE LIST
# ============================================================

@app.get(
    "/api/course/results/{task_id}/files"
)
async def get_result_files(
    task_id: str
):

    if task_id not in tasks:

        raise HTTPException(
            status_code=404,
            detail="Task not found"
        )


    task = tasks[
        task_id
    ]


    exp_dir = (
        Path("./exp")
        /
        task["exp_name"]
    )


    # --------------------------------------------------------
    # Folder not created yet
    # --------------------------------------------------------

    if not exp_dir.exists():

        return {

            "task_id":
                task_id,

            "exp_name":
                task["exp_name"],

            "files":
                [],

            "status":
                task["status"],

            "total_files":
                0
        }


    files = []


    # --------------------------------------------------------
    # Recursively list files
    # --------------------------------------------------------

    for file_path in (
        exp_dir.rglob("*")
    ):

        if (
            not file_path.is_file()
            or
            file_path.name.startswith(".")
        ):

            continue


        try:

            stat = (
                file_path.stat()
            )


            files.append({

                "name":
                    file_path.name,

                "path":
                    file_path
                    .relative_to(
                        exp_dir
                    )
                    .as_posix(),

                "size":
                    stat.st_size,

                "type":
                    file_path.suffix,

                "modified":
                    datetime
                    .fromtimestamp(
                        stat.st_mtime
                    )
                    .isoformat()
            })


        except OSError:

            continue


    files.sort(
        key=lambda item:
            item["path"]
    )


    return {

        "task_id":
            task_id,

        "exp_name":
            task["exp_name"],

        "files":
            files,

        "status":
            task["status"],

        "total_files":
            len(files)
    }


# ============================================================
# DOWNLOAD GENERATED FILE
# ============================================================

@app.get(
    "/api/course/results/{task_id}/download/{file_path:path}"
)
async def download_file(
    task_id: str,
    file_path: str
):

    if task_id not in tasks:

        raise HTTPException(
            status_code=404,
            detail="Task not found"
        )


    exp_dir = (

        Path("./exp")
        /
        tasks[task_id][
            "exp_name"
        ]

    ).resolve()


    full_path = (

        exp_dir
        /
        file_path

    ).resolve()


    # --------------------------------------------------------
    # Prevent ../ path traversal
    # --------------------------------------------------------

    try:

        full_path.relative_to(
            exp_dir
        )

    except ValueError:

        raise HTTPException(
            status_code=400,
            detail="Invalid file path"
        )


    if not full_path.is_file():

        raise HTTPException(
            status_code=404,
            detail="File not found"
        )


    return FileResponse(

        str(full_path),

        filename=
            full_path.name,

        media_type=
            "application/octet-stream"
    )


# ============================================================
# CATALOG UPLOAD
# ============================================================

@app.post(
    "/api/catalog/upload"
)
async def upload_catalog(
    file: UploadFile = File(...)
):

    # --------------------------------------------------------
    # Validate extension
    # --------------------------------------------------------

    if (
        not file.filename
        or
        not file.filename
            .lower()
            .endswith(".json")
    ):

        raise HTTPException(

            status_code=400,

            detail=
                "Please upload a .json file"
        )


    # --------------------------------------------------------
    # Read JSON
    # --------------------------------------------------------

    try:

        content = (
            await file.read()
        )


        data = json.loads(

            content.decode(
                "utf-8"
            )
        )


    except (
        UnicodeDecodeError,
        json.JSONDecodeError
    ):

        raise HTTPException(

            status_code=400,

            detail=
                "Invalid UTF-8 JSON file"
        )


    # --------------------------------------------------------
    # Save catalog
    # --------------------------------------------------------

    catalog_dir = Path(
        "catalog"
    )


    catalog_dir.mkdir(
        exist_ok=True
    )


    safe_original = Path(
        file.filename
    ).name


    filename = (

        "uploaded_"
        +
        uuid.uuid4()
            .hex[:8]
        +
        "_"
        +
        safe_original
    )


    path = (
        catalog_dir
        /
        filename
    )


    path.write_text(

        json.dumps(
            data,
            indent=2,
            ensure_ascii=False
        ),

        encoding="utf-8"
    )


    return {

        "success":
            True,

        "filename":
            filename
    }


# ============================================================
# MANUAL PPTX CONVERSION ENDPOINT
# ============================================================

@app.post(
    "/api/course/convert-pptx/{task_id}"
)
async def convert_to_pptx(
    task_id: str
):

    if task_id not in tasks:

        raise HTTPException(
            status_code=404,
            detail="Task not found"
        )


    from src.latex_to_pptx import (
        LaTeXToPPTXConverter
    )


    exp_dir = (

        Path("./exp")
        /
        tasks[task_id][
            "exp_name"
        ]
    )


    converter = (
        LaTeXToPPTXConverter()
    )


    # Conversion can also block,
    # therefore use a worker thread.

    results = await asyncio.to_thread(

        converter.convert_directory,

        str(exp_dir)
    )


    return {

        "task_id":
            task_id,

        "converted_files":
            len(results),

        "files":
            results
    }


# ============================================================
# INTERACTIVE WEB-COPILOT WORKFLOW
# ============================================================

def run_interactive_copilot_task(
    task_id: str,
    request: CourseRequest
):
    """
    Synchronous worker executed in a background thread.

    Flow:
        1. Generate foundation + syllabus + chapter list.
        2. Generate one chapter.
        3. Pause and wait for browser feedback.
        4. Approve -> next chapter.
           Revise -> regenerate the same chapter with feedback.
        5. After all chapters, compile and optionally create PPTX.
    """
    control = copilot_controls[task_id]

    original_stdout = sys.stdout
    capture = LogCapture(task_id, original_stdout)

    copilot_path = None

    try:
        update_task(
            task_id,
            status="running",
            progress=5,
            current_stage="Preparing Copilot workflow"
        )

        put_log(task_id, "Starting interactive Copilot generation")
        put_log(task_id, f"Course: {request.course_name}")
        put_log(task_id, f"Model: {request.model_name}")

        # Persist the preferences generated by the frontend.
        copilot_dir = Path("copilot")
        copilot_dir.mkdir(exist_ok=True)
        copilot_path = copilot_dir / f"copilot_{task_id}.json"
        copilot_data = request.copilot_data or {}
        copilot_path.write_text(
            json.dumps(copilot_data, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
        put_log(task_id, f"Copilot configuration saved to: {copilot_path}")

        exp_dir = Path("./exp") / request.exp_name
        exp_dir.mkdir(parents=True, exist_ok=True)

        # Use the existing ADDIE implementation directly so the chapter
        # loop can pause between chapters.
        addie = ADDIE(
            course_name=request.course_name,
            model_name=request.model_name,
            copilot=True,
            catalog=False,
            data_copilot=copilot_data,
        )

        runner = ADDIERunner(
            addie,
            output_dir=str(exp_dir),
            resume=False
        )

        sys.stdout = capture

        update_task(
            task_id,
            progress=8,
            current_stage="Generating course foundation"
        )

        runner.setup()
        runner.run_foundation_deliberations()

        if not runner.chapters:
            raise RuntimeError(
                "No chapters were generated from the syllabus."
            )

        total = len(runner.chapters)

        update_task(
            task_id,
            copilot_total_chapters=total,
            current_stage=f"Chapter development: {total} chapters found"
        )

        # --------------------------------------------------------
        # Chapter-by-chapter interactive loop
        # --------------------------------------------------------
        for chapter_idx, chapter in enumerate(runner.chapters):
            chapter_number = chapter_idx + 1
            chapter_dir = os.path.join(
                str(exp_dir),
                f"chapter_{chapter_number}"
            )
            os.makedirs(chapter_dir, exist_ok=True)

            while True:
                control["event"].clear()
                control["action"] = None
                control["feedback"] = ""

                revision_count = control["revision_count"]

                update_task(
                    task_id,
                    status="running",
                    progress=min(
                        65 + int((chapter_idx / max(total, 1)) * 29),
                        94
                    ),
                    current_stage=(
                        f"Generating Chapter {chapter_number}/{total}: "
                        f"{chapter['title']}"
                    ),
                    copilot_waiting=False,
                    copilot_chapter_number=chapter_number,
                    copilot_chapter_title=chapter["title"],
                    copilot_revision_count=revision_count,
                )

                put_log(
                    task_id,
                    f"Generating Chapter {chapter_number}/{total}: "
                    f"{chapter['title']}"
                )

                chapter_feedback = ""
                if revision_count > 0:
                    # The previous response's feedback is stored before
                    # the event is released.
                    chapter_feedback = control.get("last_feedback", "")

                runner._run_slides_generation_with_retry(
                    chapter,
                    chapter_idx,
                    chapter_dir,
                    chapter_feedback=chapter_feedback
                )

                # Tell frontend that the chapter is ready for review.
                update_task(
                    task_id,
                    status="awaiting_review",
                    progress=min(
                        65 + int(((chapter_idx + 1) / max(total, 1)) * 29),
                        94
                    ),
                    current_stage=(
                        f"Chapter {chapter_number}/{total} ready for review"
                    ),
                    copilot_waiting=True,
                    copilot_chapter_number=chapter_number,
                    copilot_chapter_title=chapter["title"],
                    copilot_revision_count=revision_count,
                )

                put_log(
                    task_id,
                    f"Chapter {chapter_number} generated. "
                    "Waiting for Copilot review."
                )

                # Wait without blocking FastAPI: this entire workflow is
                # already running in asyncio.to_thread().
                control["event"].wait()

                action = control.get("action")
                feedback = control.get("feedback", "")

                if action == "revise":
                    control["last_feedback"] = feedback
                    put_log(
                        task_id,
                        "Revising current chapter using your feedback."
                    )
                    continue

                # Approved.
                put_log(
                    task_id,
                    f"Chapter {chapter_number} approved."
                )
                break

        # --------------------------------------------------------
        # Compile after all chapters have been approved
        # --------------------------------------------------------
        update_task(
            task_id,
            status="running",
            progress=95,
            current_stage="Compiling approved course files",
            copilot_waiting=False
        )

        from src.compile import LaTeXCompiler
        compiler = LaTeXCompiler(str(exp_dir))
        compiler.compile_all()

        if request.generate_pptx:
            update_task(
                task_id,
                progress=97,
                current_stage="Generating PowerPoint files"
            )

            put_log(task_id, "Generating PPTX slides...")

            from src.latex_to_pptx import LaTeXToPPTXConverter
            converter = LaTeXToPPTXConverter()
            converter.convert_directory(str(exp_dir))

        update_task(
            task_id,
            status="completed",
            progress=100,
            current_stage="Completed",
            copilot_waiting=False
        )

        put_log(
            task_id,
            "Interactive Copilot course generation completed successfully."
        )

    except Exception as error:
        error_message = str(error)
        put_log(task_id, f"ERROR: {error_message}")

        update_task(
            task_id,
            status="failed",
            error=error_message,
            current_stage=f"Failed: {error_message}",
            copilot_waiting=False
        )

    finally:
        capture.flush()
        sys.stdout = original_stdout
        copilot_controls.pop(task_id, None)


# ============================================================
# ACTUAL GENERATION WORKER
# ============================================================

async def run_generation_task(
    task_id: str,
    request: CourseRequest
):

    """
    This is the critical fix.

    run_instructional_design() is synchronous and slow.

    Calling it directly inside an async FastAPI background
    function can block FastAPI's event loop.

    When that happened:
        - /status could not respond
        - /logs could not stream
        - frontend remained at 0%
        - Live Logs remained empty

    asyncio.to_thread() runs ADDIE/Qwen outside the FastAPI
    event loop so the frontend remains responsive.
    """


    original_stdout = (
        sys.stdout
    )


    capture = LogCapture(
        task_id,
        original_stdout
    )


    temp_catalog_path: Optional[
        Path
    ] = None

    temp_copilot_path: Optional[
        Path
    ] = None

    try:

        # ====================================================
        # STARTING
        # ====================================================

        update_task(

            task_id,

            status="running",

            progress=5,

            current_stage=
                "Preparing local Qwen workflow"
        )


        put_log(
            task_id,
            "Starting local course generation"
        )


        put_log(
            task_id,
            f"Course: {request.course_name}"
        )


        put_log(
            task_id,
            f"Model: {request.model_name}"
        )


        put_log(
            task_id,
            f"Experiment: {request.exp_name}"
        )

        # Copilot uses a dedicated interactive workflow. It pauses after
        # every chapter and waits for the browser to approve or request changes.
        if request.copilot:
            await asyncio.to_thread(
                run_interactive_copilot_task,
                task_id,
                request
            )
            return


        # ====================================================
        # CATALOG
        # ====================================================

        catalog_source = (
            request.catalog
        )
        

        if request.catalog_data:

            catalog_dir = Path(
                "catalog"
            )


            catalog_dir.mkdir(
                exist_ok=True
            )


            catalog_source = (
                f"temp_{task_id}"
            )


            temp_catalog_path = (

                catalog_dir
                /
                f"{catalog_source}.json"
            )


            temp_catalog_path.write_text(

                json.dumps(
                    request.catalog_data,
                    indent=2,
                    ensure_ascii=False
                ),

                encoding="utf-8"
            )

# ====================================================
# COPILOT
# ====================================================

        copilot_source = None

        if request.copilot:

            copilot_dir = Path(
                "copilot"
            )

            copilot_dir.mkdir(
                exist_ok=True
            )

            copilot_source = (
                f"temp_{task_id}"
            )

            temp_copilot_path = (

                copilot_dir
                /
                f"{copilot_source}.json"
            )

            temp_copilot_path.write_text(

                json.dumps(
                    request.copilot_data or {},
                    indent=2,
                    ensure_ascii=False
                ),

                encoding="utf-8"
            )

            put_log(
                task_id,
                "Copilot preferences loaded from frontend."
            )
        # ====================================================
        # ADDIE START
        # ====================================================

        update_task(

            task_id,

            progress=8,

            current_stage=
                "Starting ADDIE workflow"
        )


        # ====================================================
        # CAPTURE STDOUT
        # ====================================================

        sys.stdout = capture


        # ====================================================
        # RUN ADDIE IN WORKER THREAD
        # ====================================================

        await asyncio.to_thread(

            run_instructional_design,

            course_name=
                request.course_name,

            copilot=copilot_source,

            catalog=
                catalog_source,

            model_name=
                request.model_name,

            exp_name=
                request.exp_name
        )


        capture.flush()


        # ====================================================
        # CHECK INTERNAL ADDIE ERRORS
        # ====================================================

        if capture.workflow_error:

            raise RuntimeError(
                capture.workflow_error
            )


        # ====================================================
        # VERIFY CHAPTER GENERATION
        # ====================================================

        exp_dir = (

            Path("./exp")
            /
            request.exp_name
        )


        chapters_file = (

            exp_dir
            /
            "processed_chapters.json"
        )


        if (
            not chapters_file.exists()
            or
            chapters_file.stat().st_size == 0
        ):

            raise RuntimeError(

                "Workflow ended without generating "
                "processed_chapters.json"
            )


        # ----------------------------------------------------
        # Read chapter file
        # ----------------------------------------------------

        try:

            chapters = json.loads(

                chapters_file.read_text(
                    encoding="utf-8"
                )
            )


        except Exception as error:

            raise RuntimeError(

                "Could not read processed chapters: "
                f"{error}"
            ) from error


        if (
            not isinstance(
                chapters,
                list
            )
            or
            not chapters
        ):

            raise RuntimeError(

                "Workflow completed but "
                "no chapters were generated"
            )


        # ====================================================
        # PPTX GENERATION
        # ====================================================

        if request.generate_pptx:

            update_task(

                task_id,

                progress=97,

                current_stage=
                    "Generating PowerPoint files"
            )


            print(
                "Generating PPTX slides..."
            )


            from src.latex_to_pptx import (
                LaTeXToPPTXConverter
            )


            converter = (
                LaTeXToPPTXConverter()
            )


            await asyncio.to_thread(

                converter.convert_directory,

                str(exp_dir)
            )


        # ====================================================
        # SUCCESS
        # ====================================================

        update_task(

            task_id,

            status=
                "completed",

            progress=
                100,

            current_stage=
                "Completed"
        )


        put_log(

            task_id,

            "Course generation "
            "completed successfully"
        )


    # ========================================================
    # FAILURE
    # ========================================================

    except Exception as error:

        error_message = str(
            error
        )


        put_log(

            task_id,

            f"ERROR: {error_message}"
        )


        update_task(

            task_id,

            status=
                "failed",

            error=
                error_message,

            current_stage=
                f"Failed: {error_message}"
        )


    # ========================================================
    # CLEANUP
    # ========================================================

    finally:

        capture.flush()


        # Restore normal terminal output

        sys.stdout = (
            original_stdout
        )


        # Remove temporary catalog

        if (
            temp_catalog_path
            and
            temp_catalog_path.exists()
        ):

            try:

                temp_catalog_path.unlink()

            except OSError:

                pass

        if (
            temp_copilot_path
            and
            temp_copilot_path.exists()
        ):

            try:

                temp_copilot_path.unlink()

            except OSError:

                pass
# ============================================================
# START SERVER
# ============================================================

if __name__ == "__main__":

    uvicorn.run(

        "api_server:app",

        host=
            "127.0.0.1",

        port=
            8000,

        reload=
            False
    )