from qqrecipes.contract import Adapter


class Wrong(Adapter):
    kind = "something-else"


ADAPTER = Wrong()
