# Hyphae is the main SDK for building TruffleOS agentic applications
# This creates AI agents that can execute code, read/write files, and interact with users
import hyphae 

# Standard Python imports for data structures and type hints
from dataclasses import dataclass
from typing import Tuple, List, Dict, Any, Union, Annotated

# Hyphae-specific imports for building agent tools and responses
from hyphae.tools.respond_to_user import RespondToUserReturnType  # Standard return type for user responses

import os, subprocess, traceback
import dataclasses
from pathlib import Path

# File upload functionality for sending files back to users
from hyphae.tools.upload_file import upload_files

# Hyphae hooks system - allows customizing the agent's lifecycle and behavior
import hyphae.hooks as hooks

# Hyphae global storage system - persistent key-value store across agent sessions
from hyphae.store import globals

# Local module containing custom prompts and context overrides
import prompts 

# HOOKS SYSTEM:
# Override the default system context with custom prompts for this coding agent
# This sets up specialized instructions for code generation and debugging
hooks.get_initial_context = prompts.get_initial_context_override

# MAIN AGENT CLASS:
# This defines a specialized coding agent with tools for file operations, 
# command execution, and external AI model integration
class Code: 
    def __init__(self):
        """
        Agent state initialization.
        
        In Hyphae, agent classes maintain state across tool calls within a conversation.
        This allows the agent to track failures and permission states.
        """
        # Permission flag for calling external AI models (like OpenAI)
        self.can_call_external_model: bool = False
        
        # Track failures to determine when external help might be needed
        self.failures = 0

    # CORE COMMUNICATION TOOL:
    # This is the primary way the agent sends responses back to users
    @hyphae.tool("Send a message back to the user with your code as markdown blocks. ", icon="message")
    @hyphae.args(
        response="The message and code to send back to the user"
    )
    def RespondToUser(self, response: str) -> RespondToUserReturnType:
        """
        SIMPLIFIED USER RESPONSE:
        This version of RespondToUser doesn't handle file attachments,
        focusing purely on text/code responses. The agent can embed code
        in markdown blocks for syntax highlighting.
        """
        r = RespondToUserReturnType()
        r.response = response
        return r
    
    # FILE SYSTEM OPERATIONS:
    # These tools allow the agent to read and write files in its container environment
    @hyphae.tool("Reads a file, execute command can also do this", icon="book.closed")
    @hyphae.args(path="The path to the file to read", max_lines="The maximum number of lines to read, leave 0 for no limit")
    def ReadFile(self, path: str, max_lines: int) -> str:
        """
        FILE READING WITH ERROR TRACKING:
        Reads files from the container filesystem and tracks failures.
        This helps determine when the agent might need external assistance.
        """
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
            self.failures += 1  # Track failures for external model decision
            return f"ReadFile Error: path {path}: {str(e)}>\nTraceback: {traceback.format_exc()}"
        
    @hyphae.args(path="The path to write the file to", content="The content to write to the file")
    def WriteFile(self, path: str, content: str) -> str:
        """
        SMART FILE WRITING WITH DIFF GENERATION:
        This internal method (not a @hyphae.tool) handles file writing intelligently:
        - Swaps parameters if they appear to be in wrong order
        - Shows diffs when overwriting existing files instead of blind overwrites
        - Creates directories as needed
        - Provides rich feedback about what changed
        """
        # Handle common parameter order mistakes (path vs content confusion)
        if len(path) > len(content):
            path, content = content, path

        # Create directory structure if needed
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)

        p = Path(path)
        try:
            if p.exists():
                # File exists - check if content is actually different
                old = p.read_text()
                if old == content:
                    return f"`{path}` unchanged; no write performed."
                
                # Generate a unified diff to show what would change
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
                # New file - write it and show the content
                p.write_text(content)
                return f"Wrote new file `{path}`.\n```{content}```"
        except Exception as e:
            self.failures += 1  # Track failures
            return f"Error writing file {path}: {e}\nTraceback: {traceback.format_exc()}"
        
    @hyphae.tool("This tool writes a file; if overwriting, it returns a unified diff instead of writing. Prefer to send the user code directly in your response and use this sparingly", icon="keyboard")
    @hyphae.args(path="The path to write the file to", content="The content to write to the file")
    def WriteFileAndSendToUser(self, path: str, content: str) -> RespondToUserReturnType:
        """
        FILE CREATION WITH USER DELIVERY:
        This tool combines file writing with automatic file delivery to the user.
        It uses the internal WriteFile method and then uploads the result.
        
        The philosophy here is "show, don't just tell" - users get both
        the diff/content preview AND the actual file.
        """
        r = RespondToUserReturnType()
        # Use the internal WriteFile method to get smart diff behavior
        r.response = Path(path).name + "\n" + self.WriteFile(path, content)
        
        # If there was an error, don't try to upload
        if r.response.startswith("Error writing file"):
            return r
            
        try:
            # Upload the file so user can download it
            uploaded_files = upload_files([path])
            for file in uploaded_files:
                # Set user-friendly filename metadata
                file.metadata.name = Path(path).name
                file.metadata.path = Path(path).name
                r.files.append(file)
        except Exception as e:
                raise RuntimeError(f"Failed to upload files: {str(e)}")
        return r
    
    # SHELL EXECUTION:
    # Allows the agent to run commands in its container environment
    @hyphae.tool("This tool executes a shell command and returns the output. For this enviroment it likely will not be necessary. ", icon="apple.terminal")
    @hyphae.args(command="The shell command to execute", timeout="The timeout (seconds) for the command execution")
    def ExecuteCommand(self, command: str, timeout: int) -> List[str]:
        """
        SHELL COMMAND EXECUTION WITH FAILURE TRACKING:
        Runs shell commands and tracks failures to help determine when
        external assistance might be needed.
        """
        print("ExecuteCommand: ", command)
        output = ""
        try:
            output = subprocess.check_output(
                command, stderr=subprocess.STDOUT, shell=True, timeout=timeout,
                universal_newlines=True)
        except subprocess.CalledProcessError as exc:
            self.failures += 1  # Track command failures
            return ["Shell Command Error (" + str(exc.returncode) + "): " + exc.output, command]
        except subprocess.TimeoutExpired:
            self.failures += 1
            return ["Shell Command Timeout", command]
        except Exception as e:
            self.failures += 1
            return ["Shell Command Error: " + str(e) + '\n Traceback:' + traceback.format_exc(), command]
        else:
            return [output, command]
        
    # EXTERNAL AI MODEL INTEGRATION:
    # These tools implement a permission-based system for calling external AI services
    
    @hyphae.tool(
            "Ask the user for permission to call a more powerful external model from OpenAI ", 
            icon="hand.raised", 
            predicate=lambda self: self.can_call_external_model == False and self.failures > 1  # Only available after multiple failures
    )
    def AskForPermissionToUseExternalModel(self, reason: str) -> RespondToUserReturnType:
        """
        PERMISSION REQUEST SYSTEM:
        This implements a smart escalation pattern - the agent only asks for
        external model access after encountering multiple failures.
        
        PREDICATE LOGIC:
        - self.can_call_external_model == False: Permission not yet granted
        - self.failures > 1: Multiple failures have occurred
        
        This prevents unnecessary external API calls and costs.
        """
        self.can_call_external_model = True  # Grant permission immediately after asking

        r = RespondToUserReturnType()
        r.response = (
            "I need to call a more powerful external model to help me with this task. "
            + reason
        )
        self.can_call_external_model = True  # Redundant but explicit
        return r
    
    @hyphae.tool("Call OpenAI for help when you need it needs it", icon="sparkles", predicate=lambda self: self.can_call_external_model == True and globals.get("openai_api_key") is not None)
    @hyphae.args(
        prompt="The question or instruction to send to OpenAI"
    )
    def AskForHelp(self, prompt: str) -> str:
        """
        EXTERNAL AI MODEL CALLING:
        This tool allows the agent to call OpenAI's models for assistance.
        
        PREDICATE REQUIREMENTS:
        1. Permission must be granted (self.can_call_external_model == True)
        2. API key must be configured (globals.get("openai_api_key") is not None)
        
        This implements a two-step security model: user permission + API key.
        """
        try:
            from openai import OpenAI
            model = "gpt-5"  # Note: This might need to be updated to a valid model
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
        """
        API KEY CONFIGURATION:
        This tool allows users to securely configure their OpenAI API key.
        
        PREDICATE LOGIC:
        - globals.get("openai_api_key") is None: No key currently set
        - self.can_call_external_model == True: Permission already granted
        
        SECURITY FEATURES:
        - Validates key format (must start with "sk-")
        - Stores in global storage (persists across conversations)
        - Only shows "sk-..." in response for security
        """
        if not key.startswith("sk-"):
            return "Error: Invalid OpenAI API key format."
        globals["openai_api_key"] = key  # Store in persistent global storage
        return "set openai_api_key sk-..."  # Don't echo the full key for security
    
# MAIN EXECUTION:
# This is the standard Hyphae app entry point      
if __name__ == "__main__":
    # hyphae.run() starts the agent runtime with our Code class instance
    # This creates a gRPC server that TruffleOS can communicate with
    hyphae.run(Code())

