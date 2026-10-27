"""A tiny stand-in for the GenLayer runtime so the contract logic can be
tested with plain pytest. It simulates: balances, payable calls, transfers,
reverts on error, and a scripted AI judge."""
import types

ADDRESS = "0xc0ffee0000000000000000000000000000000001"
ledger = {}


def move(src, dst, amount):
    if ledger.get(src, 0) < amount:
        raise RuntimeError("insufficient balance")
    ledger[src] = ledger.get(src, 0) - amount
    ledger[dst] = ledger.get(dst, 0) + amount


class TreeMap(dict):
    def __class_getitem__(cls, item):
        return cls


def u256(v=0):
    return int(v)


class Address(str):
    pass


class _Message:
    sender_address = ""
    value = 0


class _Write:
    def __call__(self, fn):
        fn._kind = "write"
        return fn

    def payable(self, fn):
        fn._kind = "payable"
        return fn


class _Public:
    write = _Write()

    @staticmethod
    def view(fn):
        fn._kind = "view"
        return fn


class Contract:
    def __new__(cls, *args, **kwargs):
        obj = super().__new__(cls)
        for name, ann in getattr(cls, "__annotations__", {}).items():
            if ann is TreeMap:
                obj.__dict__[name] = TreeMap()
            elif ann is u256:
                obj.__dict__[name] = 0
        return obj


def contract_interface(cls):
    class Proxy:
        def __init__(self, addr):
            self.addr = str(addr).lower()

        def emit_transfer(self, value, on="finalized"):
            move(ADDRESS, self.addr, int(value))

    return Proxy


class _Web:
    pages = {}

    @staticmethod
    def render(url, mode="text"):
        if url not in _Web.pages:
            raise Exception("page unreachable")
        return _Web.pages[url]


class _Nondet:
    web = _Web
    judge_reply = ""

    @staticmethod
    def exec_prompt(prompt):
        return _Nondet.judge_reply


class _EqPrinciple:
    @staticmethod
    def prompt_comparative(fn, principle):
        return fn()


gl = types.SimpleNamespace(
    Contract=Contract,
    public=_Public(),
    message=_Message,
    nondet=_Nondet,
    eq_principle=_EqPrinciple,
    contract_interface=contract_interface,
)
