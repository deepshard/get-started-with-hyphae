# Building Your First Hyphae App: Personal Research Assistant

Welcome to the Hyphae, the SDK for TruffleOS! In this tutorial, we'll build a complete Personal Research Assistant app from scratch, showcasing all the powerful features of the Hyphae framework.

## What You'll Build

By the end of this tutorial, you'll have created a research assistant that can:
- Search multiple sources (web, academic papers, news)
- Take and organize notes
- Generate comprehensive reports
- Handle file operations
- Manage complex research workflows

## Prerequisites

Make sure you have Hyphae installed following the main README.MD setup instructions.

## Step 1: Setting Up Your App Structure

### Using the Template

Every Hyphae app starts with the same basic structure. Let's use the provided template to get started quickly.

1. **Clone this repo**
    ```bash
    git clone https://github.com/deepshard/get-started-with-hyphae.git
    mkdir your-app-directory
    ```
1. **Copy the Template Directory**
   ```bash
   cp -r GettingStarted/Template path-to-your/app-directory
   cd path-to-your/app-directory
   ```
   open your directoey with your choice of IDE (VSCode, Cursor etc.)

2. **Understand the Template Files**

   Your new app directory contains these essential files:

   #### `app.json` - App Configuration
   ```json
   {
       "app_uuid": "",
       "metadata": {
           "name": "Your App Name",
           "description": "Your App Description", 
           "icon": "your-icon.png"
       },
       "protocol_version": 0,
       "runtime": {
           "env": [],
           "cwd": "/opt/your-app-name",
           "cmd": [
               "python3",
               "/opt/your-app-name/main.py"
           ]
       }
   }
   ```
   
   **Purpose:** This file defines your app's metadata and runtime configuration. It tells Hyphae:
   - Your app's name and description (shown in the UI)
   - The icon to display
   - Where to run your app and what command to execute
   - Environment variables and working directory

   #### `Truffile` - Container Configuration
   ```dockerfile
   FROM hyphaehyphae/alpine-python:arm64
   
   RUN mkdir -p /opt/your-app-name
   
   # Dependencies - add yours here
   RUN pip3 install --no-cache-dir pandas requests tabulate feedparser 
   
   COPY main.py /opt/your-app-name/main.py
   COPY hyphae-1.0.1-py3-none-any.whl /tmp/hyphae-1.0.1-py3-none-any.whl
   RUN pip3 install --no-cache-dir --force-reinstall /tmp/hyphae-1.0.1-py3-none-any.whl
   
   COPY *.py /opt/your-app-name
   
   WORKDIR /opt/your-app-name
   CMD ["python3", "/opt/your-app-name/main.py"]
   ```
   
   **Purpose:** This is like a Dockerfile that defines the container environment where your app runs. It:
   - Starts from a Python-enabled base image
   - Installs your dependencies 
   - Copies your code into the container
   - Sets up the runtime environment

   #### `main.py` - Your App Code
   ```python
   your code goes here!
   ```
   
   **Purpose:** This is where you'll write your actual Hyphae app. It contains your tool definitions and app logic.

   #### `your-icon.png` - App Icon
   **Purpose:** A visual icon for your app (PNG format, recommended 512x512px)

### Customize Your Template

1. **Edit `app.json`:**
   ```json
   {
       "app_uuid": "",
       "metadata": {
           "name": "Personal Research Assistant",
           "description": "AI-powered research assistant that helps you find, analyze, and organize information from multiple sources",
           "icon": "research-icon.png"
       },
       "protocol_version": 0,
       "runtime": {
           "env": [],
           "cwd": "/opt/research",
           "cmd": [
               "python3", 
               "/opt/research/research.py"
           ]
       }
   }
   ```

2. **Update the `Truffile`:**
   ```dockerfile
    FROM hyphaehyphae/alpine-python:arm64

    RUN mkdir -p /opt/research

    RUN pip3 install --no-cache-dir ddgs python-weather pytrends pandas requests tabulate feedparser 

    COPY research.py /opt/research/research.py

    COPY hyphae-1.0.1-py3-none-any.whl /tmp/hyphae-1.0.1-py3-none-any.whl
    RUN pip3 install --no-cache-dir --force-reinstall /tmp/hyphae-1.0.1-py3-none-any.whl

    COPY *.py /opt/research

    WORKDIR /opt/research
    CMD ["python3", "/opt/research/research.py"]

   ```

3. **Add whatever icon file you would like it must be a 256x256 png:**

## Step 2: Creating Your First Hyphae App

Now let's build the foundation of our Research Assistant. Replace the contents of `main.py` with this initial code from our tested research.py:

```python
from dataclasses import dataclass
from typing import Tuple, List, Dict, Any, Union, Annotated
import hyphae

import asyncio
import requests
import time

from hyphae.tools.respond_to_user import RespondToUserReturnType
from truffle.common.file_pb2 import AttachedFile
import traceback
import os
import subprocess

import dataclasses
from pathlib import Path

from truffle.hyphae.context_pb2 import Context
from truffle.infer.convo.conversation_pb2 import Conversation, Message

from hyphae.infer import get_inference_client, find_model_for_summarization
from hyphae.runtime import context_helpers
from hyphae.tools.upload_file import upload_files

from perplexity import PerplexitySearcher
from truffle.infer.irequest_pb2 import IRequest
from truffle.infer.iresponse_pb2 import IResponse
import hyphae.hooks as hooks

class Research: 
    def __init__(self):
        self.notepad : str = ""
        self.asked_followup : bool = False
        self.start_time = time.time()
        self.min_duration = 5 * 60  # 5 minutes
    
    def has_full_tool_access(self) -> bool:
        return self.asked_followup

    def can_respond_to_user(self) -> bool:
        return self.has_full_tool_access() and self.min_duration < (time.time() - self.start_time)

    @hyphae.tool("Send a message back to the user, usually after performing a task with many tool calls", 
                 icon="message",
                predicate=lambda self: self.can_respond_to_user() == True or self.asked_followup == False
            )
    @hyphae.args(
        response="The message to send back to the user,",
        files="absolute paths to files within your enviroment to send back to the user, if any"
    )
    def RespondToUser(self, response: str, files: List[str]) -> RespondToUserReturnType:
        r = RespondToUserReturnType()
        r.response = response
        self.asked_followup = True
        self.start_time = time.time()  # reset start time to now, so they have to wait again
        try:
            if files and len(files) > 0:
                uploaded_files = upload_files(files)
                for file in uploaded_files:
                    r.files.append(file)
        except Exception as e:
                raise RuntimeError(f"Failed to upload files: {str(e)}")
        print(r)
        return r

if __name__ == "__main__":
    hyphae.run(Research())
```

### Understanding This Research App Foundation

Let's break down what each part does and why we made these design decisions:

#### 1. **Imports**
```python
from hyphae.tools.respond_to_user import RespondToUserReturnType
from hyphae.tools.upload_file import upload_files
from hyphae.infer import get_inference_client, find_model_for_summarization
from hyphae.runtime import context_helpers
import hyphae.hooks as hooks
```

**Why we include these:**
- `RespondToUserReturnType` - Allows sending both text and files back to users
- `upload_files` - Enables file sharing functionality
- `get_inference_client` and AI tools - For advanced AI capabilities like summarization
- `context_helpers` - For managing conversation context
- `hooks` - For customizing the AI's behavior and system prompts

#### 2. **Smart State Management**
```python
def __init__(self):
    self.notepad : str = ""
    self.asked_followup : bool = False
    self.start_time = time.time()
    self.min_duration = 5 * 60  # 5 minutes
```

**Design decisions explained:**
- **`notepad`** - Persistent storage for research notes across tool calls
- **`asked_followup`** - Tracks conversation state to create a natural research flow
- **`start_time` & `min_duration`** - Implements a minimum research time before allowing responses, encouraging thorough exploration

#### 3. **Advanced Predicate System**
```python
def has_full_tool_access(self) -> bool:
    return self.asked_followup

def can_respond_to_user(self) -> bool:
    return self.has_full_tool_access() and self.min_duration < (time.time() - self.start_time)
```

**How predicates work:** Predicates are simple functions that return `True` or `False` to show/hide tools based on your app's current state. This creates dynamic interfaces that change as users progress through workflows.

**Why this workflow design:**
- **Progressive disclosure** - Tools unlock as the research session progresses
- **Quality control** - Ensures the AI does substantial research before responding
- **Natural conversation flow** - Mimics how human researchers work (explore first, then summarize)

**Real examples from our research app:**

```python
# Simple predicate - tool only shows after initial interaction
@hyphae.tool("Take notes", icon="pencil.tip", predicate=lambda self: self.has_full_tool_access())
def TakeNote(self, note: str) -> str:
    self.notepad += note + "\n"
    return "Added note.\n Current notes: \n" + str(self.notepad)

# Complex predicate - tool shows in different conditions
@hyphae.tool("Send message to user", 
            predicate=lambda self: self.can_respond_to_user() == True or self.asked_followup == False)
def RespondToUser(self, response: str, files: List[str]) -> RespondToUserReturnType:
    # Tool logic here...
```

**Adding External Tools and Services:**

You can easily integrate external services by adding separate files. For example, our `perplexity.py` shows how to call other AI models:

```python
# In perplexity.py
class PerplexitySearcher:
    def run(self, query: str) -> str:
        # Makes API call to Perplexity AI
        return response.json()["choices"][0]["message"]["content"]

# In your main research.py  
from perplexity import PerplexitySearcher

@hyphae.tool("Search with Perplexity AI", predicate=lambda self: self.has_full_tool_access())
def PerplexitySearch(self, query: str) -> str:
    return PerplexitySearcher().run(query)
```

This pattern lets you:
- Keep your code organized in separate files
- Integrate any external API or service
- Ask other AI models for help when needed
- Build complex multi-step workflows

#### 4. **Sophisticated Tool Definition**
```python
@hyphae.tool("Send a message back to the user, usually after performing a task with many tool calls", 
             icon="message",
            predicate=lambda self: self.can_respond_to_user() == True or self.asked_followup == False
        )
@hyphae.args(
    response="The message to send back to the user,",
    files="absolute paths to files within your enviroment to send back to the user, if any"
)
def RespondToUser(self, response: str, files: List[str]) -> RespondToUserReturnType:
```

**Key design elements:**
- **Complex predicate logic** - Tool availability depends on multiple conditions
- **File attachment support** - Can send research reports, documents, etc.
- **State updates** - Tool calls modify app state for workflow progression

#### 5. **File Handling**
```python
try:
    if files and len(files) > 0:
        uploaded_files = upload_files(files)
        for file in uploaded_files:
            r.files.append(file)
except Exception as e:
        raise RuntimeError(f"Failed to upload files: {str(e)}")
```

**Why this approach:**
- **Robust error handling** - Graceful failure with informative messages
- **Optional file support** - Files are optional, won't break if none provided
- **Proper file management** - Uses Hyphae's built-in file upload system

#### 6. **Advanced Context Management**

You can control the AI model's system prompt and behavior using Hyphae's hook system. See our example in `Research/research.py` for how to:
- Override the initial context with custom instructions
- Implement context compression for long conversations
- Set up app lifecycle hooks

This gives you complete control over how the AI behaves within your app.

### Test Your Research App Foundation

At this point, you have a basic research app foundation that demonstrates:

1. **State-driven workflows** - Tools appear/disappear based on research progress
2. **Time-based controls** - Minimum research duration before responses
3. **File operations** - Can send research documents back to users
4. **Professional error handling** - Robust exception management
5. **Extensible architecture** - Ready for additional research tools

## What's Next?

In the following sections, we'll add the research tools to this foundation:
- Web search with DuckDuckGo
- Academic paper search
- Note-taking and organization
- Report generation
- News and trends analysis

See examples for these tools and more apps in example_apps. Theres more coming!

