import hyphae 

    
from dataclasses import dataclass
    

from typing import Tuple, List, Dict, Any, Union, Annotated


from hyphae.tools.respond_to_user import RespondToUserReturnType

import os, subprocess, traceback
import dataclasses
from pathlib import Path

from hyphae.tools.upload_file import upload_files
import hyphae.hooks as hooks
from hyphae.store import globals
import prompts 

hooks.get_initial_context = prompts.get_initial_context_override

class Code: 
    def __init__(self):
        self.can_call_external_model : bool = False
        self.failures = 0
    @hyphae.tool("Send a message back to the user with your code as markdown blocks. ", icon="message")
    @hyphae.args(
        response="The message and code to send back to the user"
    )
    def RespondToUser(self, response: str) -> RespondToUserReturnType:
        r = RespondToUserReturnType()
        r.response = response
        return r
    
    @hyphae.tool("Reads a file, execute command can also do this", icon="book.closed")
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
            self.failures += 1
            return f"ReadFile Error: path {path}: {str(e)}>\nTraceback: {traceback.format_exc()}"
        
    @hyphae.args(path="The path to write the file to", content="The content to write to the file")
    def WriteFile(self, path: str, content: str) -> str:
        if len(path) > len(content):
            path, content = content, path

        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)

        p = Path(path)
        try:
            if p.exists():
                old = p.read_text()
                if old == content:
                    return f"`{path}` unchanged; no write performed."
                import difflib
                diff = "\n".join(
                    difflib.unified_diff(
                        old.splitlines(),
                        content.splitlines(),
                        fromfile=f"a/{p.name}",
                        tofile=f"b/{p.name}",
                        lineterm=""
                    )
                )
                if not diff.strip():
                    return f"`{path}` diff empty; no write performed."
                return "```patch\n" + diff + "\n```"
            else:
                p.write_text(content)
                return f"Wrote new file `{path}`.\n```{content}```"
        except Exception as e:
            self.failures += 1
            return f"Error writing file {path}: {e}\nTraceback: {traceback.format_exc()}"
        
    @hyphae.tool("This tool writes a file; if overwriting, it returns a unified diff instead of writing. Prefer to send the user code directly in your response and use this sparingly", icon="keyboard")
    @hyphae.args(path="The path to write the file to", content="The content to write to the file")
    def WriteFileAndSendToUser(self, path: str, content: str) -> RespondToUserReturnType:
        r = RespondToUserReturnType()
        r.response = Path(path).name + "\n" + self.WriteFile(path, content)
        if r.response.startswith("Error writing file"):
            return r
        try:
            uploaded_files = upload_files([path])
            for file in uploaded_files:
                file.metadata.name = Path(path).name
                file.metadata.path = Path(path).name
                r.files.append(file)
        except Exception as e:
                raise RuntimeError(f"Failed to upload files: {str(e)}")
        return r
    
    @hyphae.tool("This tool executes a shell command and returns the output. For this enviroment it likely will not be necessary. ", icon="apple.terminal")
    @hyphae.args(command="The shell command to execute", timeout="The timeout (seconds) for the command execution")
    def ExecuteCommand(self, command: str, timeout: int) -> List[str]:
        print("ExecuteCommand: ", command)
        output = ""
        try:
            output = subprocess.check_output(
                command, stderr=subprocess.STDOUT, shell=True, timeout=timeout,
                universal_newlines=True)
        except subprocess.CalledProcessError as exc:
            self.failures += 1
            return ["Shell Command Error (" + str(exc.returncode) + "): " + exc.output, command]
        except subprocess.TimeoutExpired:
            self.failures += 1
            return ["Shell Command Timeout", command]
        except Exception as e:
            self.failures += 1
            return ["Shell Command Error: " + str(e) + '\n Traceback:' + traceback.format_exc(), command]
        else:
            return [output, command]
        
    @hyphae.tool(
            "Ask the user for permission to call a more powerful external model from OpenAI ", 
            icon="hand.raised", 
            predicate=lambda self: self.can_call_external_model == False and self.failures > 1 
    )
    def AskForPermissionToUseExternalModel(self, reason : str ) -> RespondToUserReturnType:
        self.can_call_external_model = True 

        r = RespondToUserReturnType()
        r.response = (
            "I need to call a more powerful external model to help me with this task. "
            + reason
        )
        self.can_call_external_model = True
        return r
    
    @hyphae.tool("Call OpenAI for help when you need it needs it", icon="sparkles", predicate=lambda self: self.can_call_external_model == True and globals.get("openai_api_key") is not None)
    @hyphae.args(
        prompt="The question or instruction to send to OpenAI"
    )
    def AskForHelp(self, prompt: str) -> str:
        try:
            from openai import OpenAI
            model = "gpt-5"
            client = OpenAI(api_key=globals.get("openai_api_key"))
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}]
            )
            return resp.choices[0].message.content 
        except Exception as e:
            return f"OpenAI Error: {str(e)}\nTraceback: {traceback.format_exc()}"

    @hyphae.tool("Set the OpenAI API key to use for external calls", icon="key", predicate=lambda self: globals.get("openai_api_key") is None and self.can_call_external_model == True)
    @hyphae.args(key="The OpenAI API key to use")
    def SetOpenAIApiKey(self, key: str) -> str:
        if not key.startswith("sk-"):
            return "Error: Invalid OpenAI API key format."
        globals["openai_api_key"] = key
        return "set openai_api_key sk-..."
    
       
if __name__ == "__main__":
    hyphae.run(Code())

