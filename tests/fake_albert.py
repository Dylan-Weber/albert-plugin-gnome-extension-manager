"""
Minimal stand-in for the ``albert`` module, which only exists inside Albert.

Implements just what the extension uses. Calls with side effects are recorded so tests can assert on
them, and ``Matcher`` is a simple case-insensitive substring/word-prefix matcher.
"""

detached_processes = []
clipboard = []
debug_messages = []


def reset():
    detached_processes.clear()
    clipboard.clear()
    debug_messages.clear()


def debug(msg):
    debug_messages.append(msg)


def runDetachedProcess(cmdln, workdir=""):
    detached_processes.append(list(cmdln))
    return 1


def setClipboardText(text):
    clipboard.append(text)


class Icon:
    @staticmethod
    def theme(name):
        return ("theme", name)


class Action:
    def __init__(self, id, text, callable):
        self.id = id
        self.text = text
        self.callable = callable


class Item:
    def __init__(self):
        pass


class RankItem:
    def __init__(self, item, score):
        self.item = item
        self.score = score


class MatchConfig:
    def __init__(self, fuzzy=False, ignore_case=True, ignore_word_order=True,
                 ignore_diacritics=True):
        self.fuzzy = fuzzy


class Match:
    def __init__(self, score):
        self.score = score

    def __bool__(self):
        return self.score is not None


class Matcher:
    def __init__(self, string, config=MatchConfig()):
        self.words = string.lower().split()

    def match(self, *strings):
        best = None
        for s in strings:
            s = s.lower()
            if all(w in s for w in self.words):
                score = len(" ".join(self.words)) / len(s) if s else 0.0
                best = score if best is None else max(best, score)
        return Match(best)


class PluginInstance:
    def __init__(self):
        pass


class GlobalQueryHandler:
    def __init__(self):
        pass
