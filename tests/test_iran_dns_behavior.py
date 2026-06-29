from __future__ import annotations

import importlib.machinery
import importlib.util
import sys
import types
from pathlib import Path


def _ensure_dns_module():
    try:
        import dns.resolver  # type: ignore[import-not-found]
        return dns.resolver
    except ModuleNotFoundError:
        dns_module = types.ModuleType("dns")
        dns_module.__path__ = []
        dns_module.__spec__ = importlib.machinery.ModuleSpec("dns", loader=None, is_package=True)

        exception_module = types.ModuleType("dns.exception")
        exception_module.__spec__ = importlib.machinery.ModuleSpec("dns.exception", loader=None)

        class DNSException(Exception):
            pass

        class Timeout(DNSException):
            pass

        exception_module.DNSException = DNSException
        exception_module.Timeout = Timeout

        rcode_module = types.ModuleType("dns.rcode")
        rcode_module.__spec__ = importlib.machinery.ModuleSpec("dns.rcode", loader=None)
        rcode_module.REFUSED = 5
        rcode_module.SERVFAIL = 2

        resolver_module = types.ModuleType("dns.resolver")
        resolver_module.__spec__ = importlib.machinery.ModuleSpec("dns.resolver", loader=None)

        class NoNameservers(DNSException):
            pass

        class NXDOMAIN(DNSException):
            pass

        class NoAnswer(DNSException):
            pass

        class Resolver:
            def __init__(self, configure=True):
                self.timeout = None
                self.lifetime = None

        resolver_module.NoNameservers = NoNameservers
        resolver_module.NXDOMAIN = NXDOMAIN
        resolver_module.NoAnswer = NoAnswer
        resolver_module.Resolver = Resolver

        dns_module.exception = exception_module
        dns_module.rcode = rcode_module
        dns_module.resolver = resolver_module
        sys.modules.update(
            {
                "dns": dns_module,
                "dns.exception": exception_module,
                "dns.rcode": rcode_module,
                "dns.resolver": resolver_module,
            }
        )
        return resolver_module


dns_resolver = _ensure_dns_module()

MODULE_PATH = Path("observers/iran-dns-behavior/observer.py")
SPEC = importlib.util.spec_from_file_location("iran_dns_behavior_observer", MODULE_PATH)
assert SPEC and SPEC.loader
iran_dns_behavior_observer = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = iran_dns_behavior_observer
SPEC.loader.exec_module(iran_dns_behavior_observer)


class NoErrorsNoNameservers(dns_resolver.NoNameservers):
    @property
    def errors(self):
        raise AttributeError("errors")

    def __str__(self) -> str:
        return "All nameservers failed to answer the query: SERVFAIL"


class NoNameserversResolver:
    def resolve(self, *args, **kwargs):
        raise NoErrorsNoNameservers


def test_classify_no_nameservers_without_errors_uses_text_servfail() -> None:
    exc = NoErrorsNoNameservers()

    assert iran_dns_behavior_observer.classify_no_nameservers(exc) == "servfail"


def test_make_query_handles_no_nameservers_without_errors() -> None:
    result = iran_dns_behavior_observer.make_query(NoNameserversResolver(), "example.ir", "A")

    assert result["status"] == "servfail"
    assert result["answer_count"] is None
    assert "SERVFAIL" in result["error"]
