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

def get_initial_context_override(initial):
    ctx = Context()
    system_blk = Context.ContextBlock(block_id="system", role=Message.ROLE_SYSTEM)
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
    ), source=Context.ContextEntry.SOURCE_APP)


compress_next_context = False
compress_next_context_guide = ""

def build_context_override( in_ctx : Context  ):
    global compress_next_context
    global compress_next_context_guide
    if not compress_next_context:
        return in_ctx
    print("Compressing context...")
    compress_next_context = False
    infer = get_inference_client()
    sum_model = find_model_for_summarization()

    initial = context_helpers.get_initial_prompt_from_context(in_ctx)

    content = context_helpers.extract_task_content_from_context(in_ctx)
    print(f"Context length before compression: {len(content)} characters")
    ir = IRequest()
    ir.model_uuid = sum_model
    ir.cfg.max_tokens = 4096
    ir.cfg.temp = 0.6
    ir.convo.messages.add(role=Message.ROLE_SYSTEM, text="You summarize the raw context of a conversation between a user and an AI assistant. Only include the content, ignore any structure/schema. The agent will use this summary to continue the conversation. Focus on key points, and be concise. Use bullet points where appropriate.")
    ir.convo.messages.add(role=Message.ROLE_USER, text="Compress the following context: \n" + content + "\n\n The original question/goal was: " + initial + "\n\n Summarize the context in concise bullet points, focusing on key points and ignoring unimportant details. Keep it under 500 words. Ensure to keep relevant to the original question/goal. " + compress_next_context_guide)
    try:
        print("Sending compression request to model...")
        response : IResponse = infer.stub.GenerateSync(ir)
        print("Received compression response. ", response)
        print(f"Context length after compression: {len(response.content)} characters")
        new_ctx = Context()
        new_ctx.blocks.append(in_ctx.blocks[0]) #system block
        user_blk = new_ctx.blocks.add()
        user_blk.block_id = "default-user"
        user_blk.role = Message.ROLE_USER
        user_blk.entries.add(text=response.content, source=Context.ContextEntry.SOURCE_APP)
    except Exception as e:
        print(f"Error during context compression: {e}\nTraceback: {traceback.format_exc()}")
        in_ctx.blocks[-1].entries.add(text="\n\n[Context compression failed, using uncompressed context. Error: " + str(e) + "]", source=Context.ContextEntry.SOURCE_APP)
        return in_ctx


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
    
    @hyphae.tool("Searches with Perplexity, an advanced AI search tool.", icon="magnifyingglass", predicate=lambda self: self.has_full_tool_access())
    @hyphae.args(
        query="The search query, write like a prompt not a google search."
    )
    def PerplexitySearch(self, query: str) -> str:
        return PerplexitySearcher().run(query)
    
    # @hyphae.tool("Compress and summarize the current context to save tokens", icon="arrow.up.right.and.arrow.down.left",  predicate=lambda self: self.has_full_tool_access())
    # @hyphae.args(guide="A guide to what to focus on when compressing the context, and what has already been accomplished")
    # def CompressContext(self, guide : str) -> str:
    #     global compress_next_context
    #     compress_next_context = True
    #     return "Context compression scheduled for next loop."
    
    @hyphae.tool("Take notes", icon="pencil.tip",  predicate=lambda self: self.has_full_tool_access())
    @hyphae.args(note="The note to take, it will be saved for future access, even when the context is compressed")
    def TakeNote(self, note: str) -> str:
        self.notepad += note + "\n"
        return "Added note.\n Current notes: \n" + str(self.notepad)
    @hyphae.tool("Read notes", icon="eyeglasses",  predicate=lambda self: self.has_full_tool_access())
    @hyphae.args(clear_after="Clear notes after reading. ")
    def ReadNotes(self, clear_after: bool) -> str:
        if clear_after is True:
            notes = self.notepad
            self.notepad = ""
            return "Current notes: \n" + str(notes)
        else:
            return "Current notes: \n" + str(self.notepad)
    
    @hyphae.tool("Search the web with DuckDuckGo", icon="globe",  predicate=lambda self: self.has_full_tool_access())
    @hyphae.args(query="The search query", num_results="How many results to return")
    def WebSearch(self, query: str, num_results: int) -> List[str]:
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
        from ddgs import DDGS
        results = DDGS().news(query, region='us-en', safesearch='off', timelimit='w', max_results=num_results)
        ret = []
        for result in results:
            sr = f"{result['title']} - {result['source']} - {result['date']}"
            sr += f"\n{result['body']}"
            ret.append(sr)
        return ret


    @hyphae.tool("Gets related keywords, and classifies the input", icon="rectangle.and.text.magnifyingglass",  predicate=lambda self: self.has_full_tool_access())
    @hyphae.args(keyword="what to get related keywords for")
    def FindRelatedKeywords(self, keyword : str) -> str:
        from pytrends.request import TrendReq
        import pandas as pd
        pytrends = TrendReq(hl='en-US', tz=300)
        data = pytrends.suggestions(keyword)
        pd.set_option('future.no_silent_downcasting', True)
        df = pd.DataFrame(data).drop(columns='mid')
        return df.to_markdown()

    @hyphae.tool("Get Google Trends", icon="chart.line.flattrend.trend.xyaxis",  predicate=lambda self: self.has_full_tool_access())
    @hyphae.args(trends="topics to get trends for, max 5")
    def GoogleTrends(self, trends : List[str]) -> str:
        from pytrends.request import TrendReq
        import pandas as pd
        if len(trends) > 5:
            trends = trends[:4]
        pytrends = TrendReq(hl='en-US', tz=300)
        pytrends.build_payload(kw_list=trends, timeframe='now 7-d')
        data = pytrends.interest_over_time()
        pd.set_option('future.no_silent_downcasting', True)
        return data.to_markdown()


    @hyphae.tool("This tool writes a file to the given path with the given content. Only use it if the user requested a report", icon="keyboard",  predicate=lambda self: self.has_full_tool_access())
    @hyphae.args(path="The path to write the file to", content="The content to write to the file")
    def WriteFile(self, path: str, content: str) -> str:
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
        print("ExecuteCommand: ", command)
        output = ""
        if command.find("pip") >= 0  or command.find("apk") >= 0:
            timeout = 300  # give it more time for installs.. model can underestimate 
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

def on_app_start(instance : Research):
    print("App starting")
    instance.start_time = time.time()
    print("Start time set to ", instance.start_time)


hooks.get_initial_context = get_initial_context_override
hooks.build_context = build_context_override

hooks.on_app_start = on_app_start

if __name__ == "__main__":
    hyphae.run(Research())