#!/usr/bin/env /home/chdavis/git/chatgpt-cli/.venv/bin/python

# Alternatives to this script:
# https://github.com/kharvd/gpt-cli
# https://github.com/0xacx/chatGPT-shell-cli

# OpenAI's API
# https://openai.com/pricing
# https://platform.openai.com/docs/api-reference/chat/
# https://github.com/openai/openai-python
# https://github.com/openai/openai-cookbook/blob/main/examples/How_to_format_inputs_to_ChatGPT_models.ipynb

BACKLOG = ...
# TODO backlog

# Switch to Python lib to enable server-side history?
# cf. https://pypi.org/project/openai
# https://platform.openai.com/docs/api-reference/
# If you've also got the 'openai' lib installed via pip in venv, you could also eg:
# $ export OPENAI_API_KEY=$(cat your_key.txt)
# $ openai api chat.completions.create -m gpt-4 -g user "list of countries by gdp"

# The Assistants API allows for conversation threads to have an ID (managed server-side) that I could resume ?
# https://github.com/openai/openai-assistants-quickstart
# https://platform.openai.com/docs/assistants/overview
# But then can I still use the normal Chat API, or do I need to use the Assistant API for everything?
# https://platform.openai.com/docs/assistants/overview?context=with-streaming
# https://platform.openai.com/docs/assistants/whats-new

# logging/history of conversations/threads
# (keep in sync with readline history?)
# Keep a week/month/quarter or so of logs?
# But note that readline is only logging user messages, not assistant replies
# Re-format them, so keep track of which 'role' was behind each message
# Default to --resume prev session if new enough. Default to --new if the last is too old.
# In between? Then prompt to resume (Default: new/don't resume)
# If logging to separate files, then also rotate the logs (can logrotate due that automatically?)

# history: give each thread a title/date-stamp/hash (and separate files in ~/.config/chatgpt/...)
# And /history to list/resume a previous history session/thread (readline completion)
# And /clear to clear the conversation/thread/start anew (reset back to just the instructions)
# And ask GPT (as 'system' user) to provide short (< 50 chars) summary of topic/question/conclusion for each.

# Readline:
# complete words from the conversation history?
# Do I need to manually keep my own dict of (long) words (without punctuation) ?

# Consider using the streaming API ? (To get incremental output/typing, like the web version)
# https://cookbook.openai.com/examples/how_to_stream_completions

# Put this file into its own repo (so that vscode uses just one venv per workspace/repo)
# Move this dir to its own repo
# http://manpages.ubuntu.com/manpages/git-filter-repo
# or
# http://manpages.ubuntu.com/manpages/git-filter-branch

# Package for PyPI / pipx

# Use logging.error and logging.warning and .info etc

# And /file to add/list attached files (text for now) (with readline completion of filenames)
# Make this run from any dir
# Either via #!/usr/bin/env /home/chdavis/git/junk/python/venv/bin/python
# Or maybe make the script setup it's own venv (?) HOWTO ?
# I guess I'm looking for how to install a module, eg:
#     /home/chdavis/git/junk/python/venv/bin/openai
# ... has a shebang that points to the venv python:
# #!/home/chdavis/git/junk/python/venv/bin/python3

# Re. uploading files, cf.
# https://platform.openai.com/docs/api-reference/files/create

# Custom instructions:
# Print them on startup ? As a reminder of what in them?
# But only if interactive mode, and not if piped input

# Allow /commands from inside the conversation
# And ability to list all the commands (and docs)
# Also a parser/regex for each command and its args

# And /model to change the model, and complete possibilities (autocomplete?)
# via: https://platform.openai.com/docs/api-reference/models/list
# And /stats to show usage/quota/spend
# And /instructions to edit custom instructions (external EDITOR)
# And /shell to run a shell command (or prefix with !)
# (But allow the assistant to see that output, so I can ask questions about it)
# Consider also echo'ing the bash session, eg via 'script' or similar, so that I can ask questions about the output of commands?
# But then we'll also want to be wary of PII
# https://platform.openai.com/docs/assistants/overview

# any way to access web browsing mode ? for up-to-date info ?
# Only via Plus on the web?


################################################################################

import argparse
import json
import logging
import os
import pprint
import readline as rl
import select
import subprocess
import sys
import textwrap
import time
from typing import Optional

import colorama
import openai
import regex
import requests
import rich.console
import rich.markdown
from colorama import Back, Fore, Style
import pyperclip
from unidecode import unidecode


INDENT = 0
def width():
    WRAP_WIDTH = os.get_terminal_size().columns
    WRAP_WIDTH = int(WRAP_WIDTH * .8)
    WRAP_WIDTH = min(100, WRAP_WIDTH)
    WRAP_WIDTH = max( 80, WRAP_WIDTH)
    return WRAP_WIDTH

pp = pprint.PrettyPrinter(indent=4, width=width(), underscore_numbers=True).pformat

rich_console = rich.console.Console()


# Min word length for saving for subsequent tab-completion
LEN_THRESH = 8

def tokenize(*strings):
    """Return a prioritized list of (long-ish) unique tokens from strings.

    Sequences of tokens in Title Case are kept as one token. That's useful for
    acronyms and proper nouns (eg names of people, organizations, etc)
    """
    counts = {}
    for s in strings:
        tokens = s.split()
        for t in tokens:
            if t.startswith('/'): continue
            t = t.lstrip('"')
            t = t.rstrip(':;,.!?"')
            if len(t) < LEN_THRESH: continue
            t = t.lower()
            counts[t] = counts.get(t, 0) + 1
        # And find all occurrences of Multiple Capitals (eg. 'United Nations')
        # And add those as single tokens, so 'uni<TAB>' will complete to 'United Nations'
        for term in regex.findall(r'((?:\p{Uppercase_Letter}\p{Lowercase_Letter}+\s*){2,})', s) :
            term = term.rstrip()
            if len(term) < LEN_THRESH: continue
            counts[term] = counts.get(term, 0) + 1

    return sorted(counts.keys(), key=lambda x: counts[x], reverse=True)


def highlight_long_tokens(string):
    """These are the tokens that will be tab-completable in readline

    So, highlight them in the response
    """

    string = regex.sub(
        # NB, an fr'string' needs to duplicate {{braces}} to escape them
        fr'\b(\w{{{LEN_THRESH},}})\b',
        Style.BRIGHT + r'\1' + Style.RESET_ALL,
        string
    )

    return string


def wrapper(string, end=''):
    """Wrap text to the terminal width

    end: set to eg two spaces ('  ') to make line breaks explicit with Markdown

    """

    # TODO: use textwrap to do the indent as well?
    WRAP_WIDTH = width()
    lines_wrapped = []
    for line in string.splitlines():
        # line_wrap = textwrap.wrap(line, WRAP_WIDTH, replace_whitespace=False, drop_whitespace=True)
        line_wrap = textwrap.wrap(line, WRAP_WIDTH, replace_whitespace=False, drop_whitespace=False)
        line_wrap = line_wrap or ['']
        # line_wrap += end
        lines_wrapped += line_wrap
    indent = ' ' * INDENT
    string = indent + (end + '\n' + indent).join(lines_wrapped)
    return string


def render(string: str) -> None:
    """Render a response string as Markdown

    Code blocks will also be syntax-highlighted.
    Code blocks will also be copied to clipboard.
    """

    # Render/print as markdown
    rich_console.print(rich.markdown.Markdown(wrapper(string, end='  ')))
    print()

    # Split on ``` and process every odd block as code, eg to copy to clipboard
    # Try to re-assemble, to also make modifications to the non-code text?
    processed = ''
    sections = string.split('```')
    for i, section in enumerate(sections):
        if i % 2 == 0:
            # Non-code block
            processed += highlight_long_tokens(section)
            continue
        else:
            lang, code = section.split('\n', 1)
            code = code.strip('\n')
            pyperclip.copy(code)
            processed += f'\n```{lang}\n' + code + '\n```\n'

    processed = wrapper(processed, end='  ')

    # Render/print as markdown
    # rich_console.print(rich.markdown.Markdown(processed))
    # print()


def get_response(
    prompt='',
    /,
    *,
    msgs=[],
    key,
    model,
    ) -> Optional[str]:
    global messages
    if not msgs:
        msgs = messages
        if prompt:
            msgs.append({ 'role': 'user', 'content': prompt })
    url = 'https://api.openai.com/v1/chat/completions'
    headers = {
        'Authorization': 'Bearer ' + key,
        'Content-Type': 'application/json',
    }
    data = {
        # 'max_tokens': 50,
        'temperature': 0,
        'model': model,
        'messages': msgs,
        # TODO the (reasoning) o1(-preview) model(s) can add this:
        # 'reasoning_effort': 'medium', # low, medium, high
        # TODO make that a /effort cmd ?
    }
    logging.debug(pp(data))
    response = requests.post(url, data=json.dumps(data), headers=headers)
    response_json = response.json()
    if 'error' in response_json:
        print(response_json['error'])
        return
    logging.debug(pp(response_json))
    content = response_json['choices'][0]['message']['content']
    msgs.append({ 'role': 'assistant', 'content': content })
    return content


def editor(content_a: str='', /) -> str:
    """Edit a (multi-line) string, by running your $EDITOR on a temp file

    TODO module
    """

    tf_name = '/tmp/' + os.path.basename(__file__).removesuffix('.py') + '.tmp'
    with open(tf_name, 'w') as tf:
        tf.write(content_a)

    # The split() is necessary because $EDITOR might contain multiple words
    subprocess.call(os.getenv('EDITOR', 'nano').split() + [tf_name])

    with open(tf_name, 'r') as tf:
        content_b = tf.read()
    os.unlink(tf_name)
    return content_b


# TODO put this in a class, and maintain the state there, eg a dict/priority queue
# And then just send new strings to it to be tokenized
# Alt. modules on PyPI ? https://pypi.org/search/?q=autocomplete
def completer(prefix: str, state: int) -> str | None :
    """"Tab-completion for readline

    Completes tokens from:
    user's readline history, assistant responses, /commands, file names, model names.

    History/conversation tokens are prioritized by frequency/length.

    Matches are accent-insensitive, but accent-preserving.
    Matches are case-insensitive, and not case-preserving.
    (unless multi-word, eg. proper nouns)

    """
    completions = []
    if not prefix:
        return None

    # Completions via (current) history session
    # But, we might want to have /commands in the history still
    items = [ rl.get_history_item(i) for i in range(1, rl.get_current_history_length() + 1)]
    for t in tokenize(*items):
        if unidecode(t).casefold().startswith(unidecode(prefix).casefold()):
            completions.append(t)

    # TODO merge history/messages, since they're overlapping?

    # TODO assistant messages are not in the readline history, so we need to keep track of them separately

    # Complete tokens from (assistant) messages / responses
    global messages
    items = [ m['content'] for m in messages if m['role'] == 'assistant' ]
    for t in tokenize(*items):
        # print(f'msg:{t}:')
        if unidecode(t).casefold().startswith(unidecode(prefix).casefold()):
            completions.append(t)

    # Complete /command names
    global commands
    # NB, make sure that completer_delims doesn't contain '/'
    if prefix.startswith('/'):
        completions += [
            '/' + cmd for cmd in commands if cmd.casefold().startswith(prefix[1:].casefold())
        ]
    elif '/' in prefix:
        # Complete file names matching ${text}*
        bn = os.path.basename(prefix)
        dir = os.path.dirname(prefix)
        if dir != '/': dir += '/'
        # print(f'\n{dir=}')
        # print(f'\n{bn=}')
        for file in os.listdir(dir):
            if not bn or unidecode(file).casefold().startswith(unidecode(bn).casefold()):
                if os.path.isdir(dir+file): file += '/'
                # print(f'\n{file=}')
                completions.append(dir + file)

    # Complete model names
    for m in commands['model']['choices']:
        if m.casefold().startswith(prefix):
            completions.append(m)

    if state < len(completions):
        return completions[state]

    if state == 0:
        # text doesn't match any possible completion
        beep()

    return None


def beep(n: int = 2):
    for _ in range(n):
        print("\a", end='', flush=True)


def hr():
    WRAP_WIDTH = width()
    print(Fore.LIGHTBLACK_EX + '\r' + '─' * WRAP_WIDTH, end='\n')


def set_terminal_title(string=''):
    prefix = 'chatgpt-cli'
    string = ' - ' + string
    sys.stdout.write('\x1b]2;' + prefix + string + '\x07')


def get_chat_topic():
    global messages
    global args
    prompt = (
            'Generate a one-line title/label/summary for this conversation so far.'
            'Based on the main question/conclusion/topic.'
            'Similar to a newspaper headline: a short question or conclusion.'
    )
    msg = { 'role': 'system', 'content': prompt }
    title = get_response(
        # Start from the first non-instruction messages
        msgs=messages[int(bool(args.instructions)):] + [ msg ],
        key=key,
        model=args.model,
    )
    return title


def usage():
    print("See:\nhttps://platform.openai.com/usage")


# User /commands
# TODO also dispatch to the methods that process the args
# TODO add an option to show/edit instructions? (easier to leave as CLI arg?)
# TODO option to set/(re-)generate the /topic of the conversation (store in history?)
# TODO add a /memory command to add/delete/list user-specific factoids (beyond custom instructions)
# Or easier to just append to custom instructions?
# cf. https://openai.com/index/memory-and-new-controls-for-chatgpt/
# Or just rename custom-instructions to 'context' or 'background' or 'global' or 'prefs' or so.
commands = {}
commands['clear'] = {
    'desc': 'Clear the conversation history',
}
commands['copy'] = {
    'desc': 'Copy the last assistant response to the clipboard',
}
commands['cp'] = commands['copy']
commands['edit'] = {
    'desc': 'Edit the last user message in external $EDITOR',
}
commands['file'] = {
    'desc': 'List/attach files to the conversation/dialogue. TODO ',
    'example': '/file ./data.csv',
}
commands['history'] = {
    'desc': 'List/resume previous conversation/dialogue. TODO ',
    # 'example': '/history 3',
}
commands['messages'] = {
    'desc': 'List the messages in this conversation/dialogue',
}
commands['msgs'] = commands['messages']
commands['model'] = {
    'desc': 'Get/set the OpenAI model to target',
    'example': '/model gpt-4-turbo',
    'choices':['gpt-3.5-turbo', 'gpt-4', 'gpt-4-turbo', 'gpt-4o', ],
    # TODO to use (reasoning) models, eg 'o1-preview', the 'system' role has to be renamed to 'developer'
}
commands['reload'] = {
    'desc': 'Reload the CLI',
}
commands['revert'] = {
    'desc': 'Revert/remove the previous user message (and assistant reply)',
}
commands['regenerate'] = {
    'desc': 'Regenerate the last response, optionally with higher temp. (percent) TODO',
    'example': '/regenerate 99',
}
commands['title'] = {
    'desc': 'Get/set a (new) title/topic of the conversation/dialogue TODO',
}
commands['usage'] = {
    'desc': 'Show the OpenAI API usage/quota/spend TODO',
}


parser = argparse.ArgumentParser()

parser.add_argument(
    '-k',
    '--keyfile',
    type=str,
    help="Path to file containing your OpenAI API key, else use env var OPENAI_API_KEY",
)
parser.add_argument(
    '-i',
    '--interactive',
    action='store_true',
    help="Continue the conversation after the first response (not compat. with piped input)",
)
parser.add_argument(
    '-f',
    '--file',
    type=str,
    action='append', # Collect into a list
    default=[],
    help="Path to a file to upload/analyze. Accepts multiple --file args.",
)
parser.add_argument(
    '--instructions',
    type=str,
    help="Path to file containing custom instructions, default: ~/.config/chatgpt/custom-instructions.txt",
    default=os.path.join(os.environ['HOME'], '.config/chatgpt/custom-instructions.txt'),
)
parser.add_argument(
    '-m',
    '--model',
    type=str,
    help="OpenAI model to target, eg: gpt-3.5-turbo , gpt-4o , etc ",
    choices=commands['model']['choices'],
    # default to most recent model
    default=commands['model']['choices'][-1],
)
parser.add_argument(
    '--history',
    type=str,
    help="Path to history file, default ~/.config/chatgpt/history.txt",
    default='~/.config/chatgpt/history.txt',
)
parser.add_argument(
    '-d',
    '--debug',
    action='store_true',
)
parser.add_argument(
        '-l',
        "--level",
        help=
        "Logging level, eg: [info, warn(ing), err(or), crit(ical), deb(ug), ]",
    )
parser.add_argument(
    'rest',
    # Suck up remaining CLI args into `rest`. This is the first input/prompt.
    nargs=argparse.REMAINDER,
)

args = parser.parse_args()

# History of all user/assistant messages in this conversation dialog
messages = []


################################################################################
# TODO put this in a main function

# Init (debug) logging
    # Running within a debugger?
args.debug = args.debug or bool(sys.gettrace())

# Logging level and defaults
args.level = args.level or (args.debug and 'DEBUG') or 'WARNING'
# Allow for prefix-matching too,
# eg warn => WARNING, deb => DEBUG, err => ERROR, crit => CRITICAL, etc
levels = logging.getLevelNamesMapping()
for level_str in levels:
    if level_str.startswith(args.level.upper()):
        args.level = level_str
level_int = levels.get(args.level, levels['WARNING'])
logging.basicConfig(filename=__file__ + '.log',
                    filemode='w',
                    level=level_int,
                    format='▼ %(asctime)s %(levelname)-8s %(lineno)4d %(funcName)-20s \n%(message)s'
                    )
logging.info('\n')


# Initialize colorama
colorama.init(autoreset=True)

# Init readline completion
rl.set_completer(completer)
rl.set_completer_delims(' ;?!*"\'') # NB, avoid . and / to complete file paths
# menu-complete: Tab cycles through completions
rl.parse_and_bind(r'TAB:menu-complete')

# TODO
# Allow shift-enter to make a soft-return/newline, rather than submitting input ?
# But this doesn't work:
# rl.parse_and_bind(r'"\\e[13;2u": "\n"')

# This should allow the user to arbitrarily expand long-words from their previous history
# But, it seems unsupported in the Python readline.
# But we can tokenize the history and add it to the completer() manually ...
# rl.parse_and_bind(r'"\e/":dabbrev-expand')

# Init readline history
args.history = os.path.expanduser(args.history)
hist_dir = os.path.dirname(args.history)
os.makedirs(hist_dir, exist_ok=True)
if not os.path.isfile(args.history):
    open(args.history, 'a').close()
rl.read_history_file(args.history)

# Enable bracketed paste mode (allows pasting multi-line content into the prompt)
os.system(r'printf "\e[?2004h"')
# Disable bracketed paste mode ? at the end ?
# os.system(r'printf "\e[?2004l"')

key = os.environ.get('OPENAI_API_KEY')
# TODO any way to verify it's a usable key (eg with a test request) ? Like verifying the model name? Or the quota/usage
if not key:
    try:
        key = open(args.keyfile).read().rstrip()
    except:
        print('\n' + Fore.RED + "Error: Set OPENAI_API_KEY or provide a keyfile" + '\n')
        parser.print_help()
        exit(1)


# Load any custom instructions
# TODO factor this out, to make it easier to reload
if args.instructions:
    args.instructions = os.path.abspath(os.path.expanduser(args.instructions))
if not os.path.isfile(args.instructions):
    args.instructions = None
else:
    logging.info(f'Custom instructions:\nfile://' + args.instructions)
    with open(args.instructions, 'r') as file:
        instructions = file.read()
        messages.append({ 'role': 'system', 'content': instructions })

# Prepend (the content of) any file(s) that the question/prompt might reference.
for file_name in args.file:
    if args.debug :
        info = '\n' + 'INFO: File to analyze: ' + Style.BRIGHT + file_name + '\n'
        print(info, file=sys.stderr)
    # TODO test the file type, only proceed if it's text/plain
    
    with open(file_name, 'r') as file:
        messages.append({
            'role': 'system',
            'content': f"File:{file_name}\n(Make use of it when answering subsequent questions)\nContent:\n\n",
        })
        messages.append({ 'role': 'system', 'content': file.read() })

# The goal of interactive mode is to allow for follow-up questions.
# If a question was given on the CLI, assume no follow-up, unless -i given
args.interactive = len(args.rest) == 0 or args.interactive
# Any question/prompt written directly on the CLI
init_input = ' '.join(args.rest)

logging.debug(pp(vars(args)))

# Check if there is any data (already) piped into stdin, if so delimit it
if select.select([sys.stdin,],[],[],0.0)[0]:
    init_input += '\n```\n'
    init_input += sys.stdin.read()
    init_input += '\n```\n'
    print('\n', init_input, '\n')
    # Interactive mode reads from stdin, so it's not compat with piped input
    args.interactive = False


if not args.interactive:
    # Just print the response, unformatted, and exit
    if response := get_response(init_input, key=key, model=args.model):
        print()
        render(response)

    sys.exit()


################################################################################
# Interactive mode:
# TODO factor this out

# NB, I tried to keep interactive mode in the case of piped input, but I failed.
# Since the piped input is on stdin, once it's consumed, it's stuck in EOF, it seems.
# But the interactive mode reads from stdin, via input(). So, these modes conflict.
# I tried to re-open stdin from /dev/tty, but that seems to break readline.
# Rather: use multi-line paste from within interactive mode, or use /edit, or use /file

# Multi-line typing?
# And how to make Shift-Enter or Alt-Enter insert a newline, rather than ending the input() ?
# And how to make Ctrl-Enter send the message, rather than ending the input() ?

# Set terminal default title (until we determine a topical title)
set_terminal_title()
title = None

# Clear/scroll screen
# print('\033c')
print()

# (User) message counter width
DIGITS = 2

while True:

    # Counts the number of user messages (since they always alternate?)
    i = len(messages) // 2 + 1
    prompt_items = [ *[]
        , '▼ #'
        # , ' ' * min(2,INDENT-DIGITS-1)
        , f'{i:{DIGITS}d}'
        # , '\n'
    ]
    prompt = ''.join(prompt_items)
    if init_input:
        user_input = init_input
        init_input = None
    else:
        user_input = None
    if user_input:
        print(Style.DIM + prompt)
        print(user_input)

    while not user_input:
        try:
            # NB, no non-printing chars/formatting codes in the input prompt.
            # Else readline miscalculates line length, which breaks editing.
            print(Style.DIM + prompt)
            user_input = input(' ' * INDENT)
            user_input = user_input.strip()
        except (KeyboardInterrupt):
            # Just cancel/reset the current line/prompt
            print('^C')
        except (KeyboardInterrupt, EOFError):
            # Ctrl-D to exit
            print()
            sys.exit()

    hist_len = rl.get_current_history_length()

    # TODO refactor this into a dispatch table, with functions for each command
    # Based on the `commands` dict
    # Use `match` to match the command name, and grab any args in an optional list
    # But, also need to decide if we allow more than one command/pattern to match
    # And if we store history and submit to GPT or not
    # Eg additional attributes for each command, like 'submit' or 'history' or 'exclusive' ?
    if False: ...
    elif match := regex.match(r'^\/model\s*([a-z0-9.-]+)?\s*$', user_input):
        # /meta commands
        print('models: ',   commands['model']['choices'])
        if match.group(1):
            if not match.group(1) in commands['model']['choices']:
                continue
            args.model = match.group(1)
        print(Fore.LIGHTBLACK_EX + f"model={args.model}")
        user_input = None
    elif match := regex.match(r'^\/file\s*(.*?)\s*$', user_input):
        # TODO list existing files, else upload new one
        print("# TODO")
    elif match := regex.match(r'^\/edit\s*(.*)\s*$', user_input):
        print(f'Editing ... ', end='', flush=True)
        if match.group(1):
            edit_content = match.group(1)
        else:
            # Get the prev input, before this /edit command
            edit_content = rl.get_history_item(hist_len-1)
            # TODO but then do we want to replace this msg in `messages` ?
        user_input = editor(edit_content)
        # TODO print with rich ?
        print(Style.DIM + '\r\n' + user_input)
        if input(Style.BRIGHT + "Submit? (Y/n): ").casefold() == 'n':
            # Remove the answer to the input() question
            rl.remove_history_item(hist_len)
            continue
        rl.add_history(user_input)
    elif match := regex.match(r'^\/reload\s*$', user_input):
        # Reload this script/source (for latest changes)
        # And show the last modification time of this file
        tl = time.localtime(os.path.getmtime(sys.argv[0]))[0:6]
        ts = "%04d-%02d-%02d %02d:%02d:%02d" % tl
        logging.debug(f"{os.getpid()=} mtime={ts} {sys.argv[0]=}")
        os.execv(sys.argv[0], sys.argv)
    elif match := regex.match(r'^\/revert\s*$', user_input):
        prev = rl.get_history_item(hist_len-1)
        rl.remove_history_item(hist_len-1) # Remove the /revert command
        rl.remove_history_item(hist_len-2) # Remove the prev user Q
        print(Style.DIM + '\r\n' + 'Removed: ' + prev)
        # TODO verify that these correspond
        if messages: messages.pop() # Remove the assistant response
        if messages: messages.pop() # Remove the user prompt
        user_input = None
    elif match := regex.match(r'^\/(messages|msgs)\s*$', user_input):
        # Dump all the messages
        for i, msg in enumerate(messages):
            print(Style.DIM + f"#{i:2d} {msg['role']:10s}:")
            print(wrapper(msg['content']) + "\n")
        continue
    elif match := regex.match(r'^\/(copy|cp)\s*$', user_input):
        # Copy the last assistant response to the clipboard
        msgs = [ m for m in messages if m['role'] == 'assistant' ]
        if msgs:
            pyperclip.copy(msgs[-1]['content'])
            print(Style.DIM + 'Copied to clipboard')
        continue
    elif match := regex.match(r'^\/clear\s*$', user_input):
        # Clear the conversation history
        # But, keep the instructions, if any were given
        del messages[int(bool(args.instructions)):]
        # clear terminal, and move cursor to bottom
        os.system('clear; tput cup "$(tput lines)"')
        title = None
        set_terminal_title()
        continue
    elif match := regex.match(r'^\/usage\s*$', user_input):
        usage()
        continue
    elif match := regex.match(r'^[?/]', user_input):
        print("/commands:")
        for cmd in sorted(commands.keys()):
            print(f"/{cmd:10s}{commands[cmd]['desc']}")
        continue
    elif match := regex.match(r'^\s*[!$]\s*(.*)', user_input):
        cmd = match.group(1)
        # Allow running (bash) functions/aliases
        # TODO doc the '$' wrapper, maybe add it as an example to the repo ?
        source = f'$ {cmd}'
        out = subprocess.run(source, shell=True, text=True, capture_output=True)
        if out.stdout:
            out.stdout = out.stdout.strip()
            print(out.stdout)
            pyperclip.copy(out.stdout)
        if out.stderr:
            print(Fore.RED + out.stderr, end='')

        messages.append( { 'role': 'user',   'content': '$ ' + cmd } )
        messages.append( { 'role': 'system', 'content': out.stdout + '\n' + out.stderr } )
        continue


    # Do this in every iteration, since we could abort any time
    rl.write_history_file(args.history)

    if user_input:
        print('... ', end='')
        # TODO allow this to be Ctrl-C interrupted (if we do streaming ...)
        if response := get_response(user_input, key=key, model=args.model):
            hr()
            render(response)

            if not title:
                title = get_chat_topic()
                set_terminal_title(title)

    user_input = None
