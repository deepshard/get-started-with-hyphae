# Standard Python imports for data structures and type hints
from dataclasses import dataclass
from typing import Tuple, List, Dict, Any, Union, Annotated

# Hyphae is the main SDK for building TruffleOS agentic applications
import hyphae

import asyncio
import requests
import time

# Hyphae-specific imports for building agent tools and responses
from hyphae.tools.respond_to_user import RespondToUserReturnType  # Standard return type for user responses
from truffle.common.file_pb2 import AttachedFile  # Protocol buffer definition for file attachments
import traceback
import os
import subprocess

import dataclasses
from pathlib import Path

# Protocol buffer imports for conversation context management
# These handle the conversation history and state between user and agent
from truffle.hyphae.context_pb2 import Context
from truffle.infer.convo.conversation_pb2 import Conversation, Message

# Hyphae inference system - allows agents to call other AI models
from hyphae.infer import get_inference_client, find_model_for_summarization
from hyphae.runtime import context_helpers
from hyphae.tools.upload_file import upload_files

# External dependency - custom Perplexity search implementation see perplexity.py
from perplexity import PerplexitySearcher

# Protocol buffer types for AI model requests and responses
from truffle.infer.irequest_pb2 import IRequest
from truffle.infer.iresponse_pb2 import IResponse

# Hyphae hooks system - allows customizing the agent's lifecycle and behavior
import hyphae.hooks as hooks

# HOOKS SYSTEM EXPLANATION:
# Hyphae provides a hooks system that allows you to customize how your agent behaves
# at different points in its lifecycle. This is powerful for creating specialized agent behaviors.

def get_initial_context_override(initial):
    """
    CONTEXT OVERRIDE HOOK:
    This function customizes the initial system prompt that the AI agent receives.
    
    The Context system in Hyphae manages conversation history as "blocks" containing messages.
    Each block has a role (SYSTEM, USER, ASSISTANT) and contains message entries.
    
    This is like setting up the agent's "personality" and instructions before it starts working.
    """
    ctx = Context()  # Create a new context object
    
    # Create a system message block - this sets the agent's behavior and instructions
    system_blk = Context.ContextBlock(block_id="system", role=Message.ROLE_SYSTEM)
    
    # Add the system prompt that defines how this research agent should behave
    system_blk.entries.add(text=(
        "You are an expert researcher and information gatherer."
        "You are given a question, task, or goal, and a set of possible functions to use to "
        "accomplish it. \n"
        "If you do not have access to research tools, you should simply ask the user follow up questions on "
        "their prompt without mentioning tools. \n"
        "If you do not have access to RespondToUser, it is implied you should continue your research.  Consider"
        "alternate pathways directly relevant to the provided task. You will have access to this tool when it is time to respond.\n"
        "The task will start with an initial exploration phase, where you get up to two tool calls to come up with "
        "follow up questions to ask the user to better understand their needs. \n"
        "After your follow up questions are answered, you will have full tool access to accomplish the task. \n"
        "You will be unable to respond to user until a minimum time has passed, and you have asked your follow up questions. \n"
        "Based on the question, you will need to make a series of function/tool calls to achieve "
        "the purpose."
        "If the given question lacks what is needed to accomplish the task, you can ask for more "
        "information with RespondToUser.\n"
        "You may receive files, which will be passed to you as file paths, usually in "
        "/root/. Try to put any files you send back to the user in the same directory as "
        "well. Ensure paths are correct when referencing them to send back to the user.\n"
        "You are inside your own secure, ephemeral personal Alpine Linux container, where you have "
        "full root "
        "access and can do whatever you need. It is okay to break system packages, etc, the "
        "container is all yours, enjoy it, call it home."
        "It is fully isolated from the rest of the system and will be destroyed after the task is "
        "completed, no worries! \n"
        "Only send back files when it warrants or was requested. \n"
        "Please only speak in function calls. Use response tools to contact the user sparingly, "
        "they want you to primarily work independently."
        "Please respond in the given JSON format:\n {\"tool\": {\"tool_name\": \"<tool_name>\", "
        "\"args\": {<tool specific args, given by the schemas below>} }\n"
    ), source=Context.ContextEntry.SOURCE_APP)  # Mark this as coming from the app (not user input)

# Global variables for context compression functionality
# Context compression helps manage long conversations by summarizing them
compress_next_context = False
compress_next_context_guide = ""

def build_context_override(in_ctx: Context):
    """
    CONTEXT BUILDING HOOK:
    This function is called when the agent needs to process conversation context.
    
    Context in Hyphae represents the entire conversation history between user and agent.
    As conversations get long, they can exceed AI model token limits, so this function
    can compress/summarize the context to keep it manageable.
    
    IRequest and IResponse are protocol buffer types for communicating with AI models:
    - IRequest: Contains the prompt, model selection, and generation settings
    - IResponse: Contains the AI model's response and metadata
    
    This allows the agent to use AI models to help manage its own conversation context.
    """
    global compress_next_context
    global compress_next_context_guide
    
    # If compression isn't needed, return the context unchanged
    if not compress_next_context:
        return in_ctx
        
    print("Compressing context...")
    compress_next_context = False
    
    # Get access to the inference system to call AI models for summarization
    infer = get_inference_client()
    sum_model = find_model_for_summarization()

    # Extract the original user question and conversation content
    initial = context_helpers.get_initial_prompt_from_context(in_ctx)
    content = context_helpers.extract_task_content_from_context(in_ctx)
    print(f"Context length before compression: {len(content)} characters")
    
    # Create a request to an AI model to summarize the conversation
    ir = IRequest()  # Create inference request
    ir.model_uuid = sum_model  # Specify which AI model to use
    ir.cfg.max_tokens = 4096   # Set maximum response length
    ir.cfg.temp = 0.6         # Set creativity/randomness level
    
    # Set up the summarization prompt
    ir.convo.messages.add(role=Message.ROLE_SYSTEM, text="You summarize the raw context of a conversation between a user and an AI assistant. Only include the content, ignore any structure/schema. The agent will use this summary to continue the conversation. Focus on key points, and be concise. Use bullet points where appropriate.")
    ir.convo.messages.add(role=Message.ROLE_USER, text="Compress the following context: \n" + content + "\n\n The original question/goal was: " + initial + "\n\n Summarize the context in concise bullet points, focusing on key points and ignoring unimportant details. Keep it under 500 words. Ensure to keep relevant to the original question/goal. " + compress_next_context_guide)
    
    try:
        print("Sending compression request to model...")
        # Call the AI model to get a compressed summary
        response: IResponse = infer.stub.GenerateSync(ir)
        print("Received compression response. ", response)
        print(f"Context length after compression: {len(response.content)} characters")
        
        # Create new compressed context with the summary
        new_ctx = Context()
        new_ctx.blocks.append(in_ctx.blocks[0])  # Keep the system block
        user_blk = new_ctx.blocks.add()
        user_blk.block_id = "default-user"
        user_blk.role = Message.ROLE_USER
        user_blk.entries.add(text=response.content, source=Context.ContextEntry.SOURCE_APP)
        
        return new_ctx
        
    except Exception as e:
        print(f"Error during context compression: {e}\nTraceback: {traceback.format_exc()}")
        # If compression fails, add an error note and return original context
        in_ctx.blocks[-1].entries.add(text="\n\n[Context compression failed, using uncompressed context. Error: " + str(e) + "]", source=Context.ContextEntry.SOURCE_APP)
        return in_ctx

# MAIN AGENT CLASS:
# This is where we define our research agent and all its capabilities (tools)
class Research: 
    def __init__(self):
        """
        Agent state initialization.
        
        In Hyphae, agent classes maintain state across tool calls within a conversation.
        This allows the agent to remember information between different tool executions.
        """
        self.notepad: str = ""  # Persistent notes that survive context compression
        self.asked_followup: bool = False  # Track if agent has asked follow-up questions
        self.start_time = time.time()  # Track when the agent started
        self.min_duration = 5 * 60  # Minimum 5 minutes before agent can respond
    
    def has_full_tool_access(self) -> bool:
        """
        PREDICATE FUNCTION:
        This controls when the agent gets access to its full set of research tools.
        Used in tool decorators to implement a phased approach to research.
        """
        return self.asked_followup

    def can_respond_to_user(self) -> bool:
        """
        PREDICATE FUNCTION:
        Controls when the agent can send responses back to users.
        Implements a time-gated approach to encourage thorough research.
        """
        return self.has_full_tool_access() and self.min_duration < (time.time() - self.start_time)

    # TOOL DEFINITIONS:
    # The @hyphae.tool decorator makes a method available as a tool the AI agent can call
    # The @hyphae.args decorator describes the parameters for the AI to understand
    
    @hyphae.tool("Send a message back to the user, usually after performing a task with many tool calls", 
                 icon="message",  # UI icon for this tool
                 predicate=lambda self: self.can_respond_to_user() == True or self.asked_followup == False  # When this tool is available
            )
    @hyphae.args(
        response="The message to send back to the user,",
        files="absolute paths to files within your enviroment to send back to the user, if any"
    )
    def RespondToUser(self, response: str, files: List[str]) -> RespondToUserReturnType:
        """
        CORE COMMUNICATION TOOL:
        This is how the agent sends messages and files back to the user.
        
        RespondToUserReturnType is a protocol buffer type that packages the response
        with any attached files in a structured way the TruffleOS system understands.
        """
        r = RespondToUserReturnType()
        r.response = response
        
        # Update agent state when responding
        self.asked_followup = True
        self.start_time = time.time()  # Reset timer after responding
        
        try:
            # Handle file uploads if any files are provided
            if files and len(files) > 0:
                uploaded_files = upload_files(files)  # Upload files to TruffleOS file system
                for file in uploaded_files:
                    r.files.append(file)  # Attach uploaded files to response
        except Exception as e:
                raise RuntimeError(f"Failed to upload files: {str(e)}")
        print(r)
        return r
    
    # EXTERNAL AI MODEL INTEGRATION:
    # This shows how agents can use external AI services alongside TruffleOS models
    @hyphae.tool("Searches with Perplexity, an advanced AI search tool.", icon="magnifyingglass", predicate=lambda self: self.has_full_tool_access())
    @hyphae.args(
        query="The search query, write like a prompt not a google search."
    )
    def PerplexitySearch(self, query: str) -> str:
        """
        EXTERNAL AI INTEGRATION:
        This demonstrates how Hyphae agents can integrate with external AI services.
        The agent can use Perplexity AI for advanced search capabilities beyond basic web search.
        """
        return PerplexitySearcher().run(query)
    
    # STATE PERSISTENCE TOOLS:
    # These tools help the agent maintain memory across context compressions
    @hyphae.tool("Take notes", icon="pencil.tip",  predicate=lambda self: self.has_full_tool_access())
    @hyphae.args(note="The note to take, it will be saved for future access, even when the context is compressed")
    def TakeNote(self, note: str) -> str:
        """
        PERSISTENT MEMORY:
        Since conversation context can be compressed/summarized, important information
        might be lost. This notepad provides persistent storage that survives compression.
        """
        self.notepad += note + "\n"
        return "Added note.\n Current notes: \n" + str(self.notepad)
        
    @hyphae.tool("Read notes", icon="eyeglasses",  predicate=lambda self: self.has_full_tool_access())
    @hyphae.args(clear_after="Clear notes after reading. ")
    def ReadNotes(self, clear_after: bool) -> str:
        """Read back stored notes, optionally clearing them after reading."""
        if clear_after is True:
            notes = self.notepad
            self.notepad = ""
            return "Current notes: \n" + str(notes)
        else:
            return "Current notes: \n" + str(self.notepad)
    
    # WEB RESEARCH TOOLS:
    # Standard web search capabilities using DuckDuckGo
    @hyphae.tool("Search the web with DuckDuckGo", icon="globe",  predicate=lambda self: self.has_full_tool_access())
    @hyphae.args(query="The search query", num_results="How many results to return")
    def WebSearch(self, query: str, num_results: int) -> List[str]:
        """
        BASIC WEB SEARCH:
        Provides standard web search functionality using DuckDuckGo.
        Returns formatted results with titles, links, and descriptions.
        """
        from ddgs import DDGS
        results = DDGS().text(query, region='wt-wt', safesearch='off', timelimit='y', max_results=num_results)
        ret = []
        print(results)
        for result in results:
            sr = f"[{result['title']}]({result['href']})"
            sr += f"\n{result['body']}"
            ret.append(sr)
        return ret

    @hyphae.tool("Get North American news articles from the last week", icon="newspaper.fill",  predicate=lambda self: self.has_full_tool_access())
    @hyphae.args(query="News search query", num_results="The number of news results to return")
    def SearchNewsArticles(self, query: str, num_results: int) -> List[str]:
        """NEWS-SPECIFIC SEARCH: Specialized search for recent news articles."""
        from ddgs import DDGS
        results = DDGS().news(query, region='us-en', safesearch='off', timelimit='w', max_results=num_results)
        ret = []
        for result in results:
            sr = f"{result['title']} - {result['source']} - {result['date']}"
            sr += f"\n{result['body']}"
            ret.append(sr)
        return ret

    # TREND ANALYSIS TOOLS:
    # Specialized tools for understanding search trends and related topics
    @hyphae.tool("Gets related keywords, and classifies the input", icon="rectangle.and.text.magnifyingglass",  predicate=lambda self: self.has_full_tool_access())
    @hyphae.args(keyword="what to get related keywords for")
    def FindRelatedKeywords(self, keyword: str) -> str:
        """
        KEYWORD ANALYSIS:
        Uses Google Trends API to find related keywords and topics.
        Helps expand research beyond the initial query terms.
        """
        from pytrends.request import TrendReq
        import pandas as pd
        pytrends = TrendReq(hl='en-US', tz=300)
        data = pytrends.suggestions(keyword)
        pd.set_option('future.no_silent_downcasting', True)
        df = pd.DataFrame(data).drop(columns='mid')
        return df.to_markdown()

    @hyphae.tool("Get Google Trends", icon="chart.line.flattrend.trend.xyaxis",  predicate=lambda self: self.has_full_tool_access())
    @hyphae.args(trends="topics to get trends for, max 5")
    def GoogleTrends(self, trends: List[str]) -> str:
        """
        TREND ANALYSIS:
        Analyzes search volume trends for topics over time.
        Useful for understanding topic popularity and timing.
        """
        from pytrends.request import TrendReq
        import pandas as pd
        if len(trends) > 5:
            trends = trends[:4]
        pytrends = TrendReq(hl='en-US', tz=300)
        pytrends.build_payload(kw_list=trends, timeframe='now 7-d')
        data = pytrends.interest_over_time()
        pd.set_option('future.no_silent_downcasting', True)
        return data.to_markdown()

    # FILE SYSTEM TOOLS:
    # Standard file operations for reading, writing, and executing commands
    @hyphae.tool("This tool writes a file to the given path with the given content. Only use it if the user requested a report", icon="keyboard",  predicate=lambda self: self.has_full_tool_access())
    @hyphae.args(path="The path to write the file to", content="The content to write to the file")
    def WriteFile(self, path: str, content: str) -> str:
        """
        FILE CREATION:
        Creates files that can be sent back to users.
        The agent runs in an isolated container with full filesystem access.
        """
        # Handle common parameter order mistakes
        if len(path) > len(content):
            x = path
            path = content 
            content = x 
        
        print("write a file", path)

        directory = os.path.dirname(path)
        if directory:  # Only create directories if there's a path specified
            os.makedirs(directory, exist_ok=True)
        
        try:
            with open(path, "w") as f:
                f.write(content)
            return f"Wrote {len(content)} bytes successfully to {os.path.basename(path)}"
        except Exception as e:
            return f"Error writing file {path}: {str(e)}\nTraceback: {traceback.format_exc()}"
        
    @hyphae.tool("Reads a file, execute command can also do this", icon="book.closed",  predicate=lambda self: self.has_full_tool_access())
    @hyphae.args(path="The path to the file to read", max_lines="The maximum number of lines to read, leave 0 for no limit")
    def ReadFile(self, path: str, max_lines: int) -> str:
        """FILE READING: Read files from the container filesystem."""
        if not os.path.exists(path):
            return f"ReadFile Error: <File {path} does not exist.>"
        try:
            with open(path, "r") as f:
                if max_lines > 0:
                    lines = f.readlines()[:max_lines]
                else:
                    lines = f.readlines()
            return "".join(lines)
        except Exception as e:
            return f"ReadFile Error: path {path}: {str(e)}>\nTraceback: {traceback.format_exc()}"
        
    @hyphae.tool("This tool executes a shell command and returns the output. For this enviroment it likely will not be necessary. ", icon="apple.terminal",  predicate=lambda self: self.has_full_tool_access())
    @hyphae.args(command="The shell command to execute", timeout="The timeout (seconds) for the command execution")
    def ExecuteCommand(self, command: str, timeout: int) -> List[str]:
        """
        SHELL EXECUTION:
        Allows the agent to run shell commands in its container environment.
        Useful for installing packages, running scripts, or system operations.
        """
        print("ExecuteCommand: ", command)
        output = ""
        # Give more time for package installations
        if command.find("pip") >= 0  or command.find("apk") >= 0:
            timeout = 300  # 5 minutes for installs
            
        try:
            output = subprocess.check_output(
                command, stderr=subprocess.STDOUT, shell=True, timeout=timeout,
                universal_newlines=True)
        except subprocess.CalledProcessError as exc:
            return ["Shell Command Error (" + str(exc.returncode) + "): " + exc.output, command]
        except subprocess.TimeoutExpired:
            return ["Shell Command Timeout", command]
        except Exception as e:
            return ["Shell Command Error: " + str(e) + '\n Traceback:' + traceback.format_exc(), command]
        else:
            return [output, command]

def on_app_start(instance: Research):
    """
    APP LIFECYCLE HOOK:
    This function is called when the agent application starts up.
    Used for initialization that needs to happen after the agent is created.
    """
    print("App starting")
    instance.start_time = time.time()
    print("Start time set to ", instance.start_time)

# HOOKS REGISTRATION:
# This is where we register our custom hook functions with the Hyphae system.
# Hooks allow you to customize the agent's behavior at key points in its lifecycle.

# Override the default system context with our custom research agent instructions
hooks.get_initial_context = get_initial_context_override

# Override the default context building to add compression capabilities
hooks.build_context = build_context_override

# Register our app startup hook
hooks.on_app_start = on_app_start

# MAIN EXECUTION:
# This is the standard Hyphae app entry point
if __name__ == "__main__":
    # hyphae.run() starts the agent runtime with our Research class instance
    # This creates a gRPC server that TruffleOS can communicate with
    hyphae.run(Research())