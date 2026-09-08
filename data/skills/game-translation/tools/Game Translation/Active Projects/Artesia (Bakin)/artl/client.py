#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
client.py - Anthropic client construction and token accounting.

An unset ANTHROPIC_API_KEY does NOT mean there are no credentials: the SDK
resolves ANTHROPIC_API_KEY -> ANTHROPIC_AUTH_TOKEN -> the profile written by
`ant auth login` -> Workload Identity Federation. So the zero-argument
constructor is the right call, and the error message points at `ant auth
status` rather than demanding a key.
"""

import os
import sys


def get_client():
    try:
        from anthropic import Anthropic
    except ImportError:
        sys.exit("ERROR: pip install anthropic")
    try:
        client = Anthropic()
    except Exception as e:
        sys.exit(
            "ERROR: could not construct an Anthropic client (%s).\n"
            "  Credentials resolve in this order: ANTHROPIC_API_KEY, "
            "ANTHROPIC_AUTH_TOKEN, an `ant auth login` profile, WIF.\n"
            "  Run `ant auth status` to see which one is active." % e)
    # The constructor does NOT fail without a key - it defers to the first
    # request, so a 200-request run would fail 200 times with a 401 instead of
    # once with a sentence. Check here.
    #
    # Claude Code's own `~/.claude/.credentials.json` is an OAuth token for the
    # CLI and is NOT read by this SDK; having Claude Code working says nothing
    # about whether this pipeline can authenticate.
    if (getattr(client, "api_key", None) or getattr(client, "auth_token", None)
            or os.environ.get("ANTHROPIC_AUTH_TOKEN")
            or os.environ.get("ARTL_SKIP_CRED_CHECK")
            or _has_cli_profile()):
        return client
    sys.exit(
        "ERROR: no API credentials found.\n"
        "  Set ANTHROPIC_API_KEY or ANTHROPIC_AUTH_TOKEN, or log in with "
        "`ant auth login`.\n"
        "  Claude Code's own ~/.claude/.credentials.json is an OAuth token for "
        "the CLI and is NOT read by the Anthropic SDK, so a working Claude "
        "Code says nothing about whether this pipeline can authenticate.\n"
        "  If you authenticate some way that sets neither attribute - Workload "
        "Identity Federation, a proxy - set ARTL_SKIP_CRED_CHECK=1 and this "
        "check gets out of the way.")


def _has_cli_profile():
    """Does an `ant auth login` profile exist?

    The SDK resolves one without setting `api_key` or `auth_token`, so checking
    those two attributes alone rejects a valid setup - the exact contradiction
    `get_client`'s own docstring warns about."""
    home = os.path.expanduser("~")
    for rel in (os.path.join(".ant", "credentials.json"),
                os.path.join(".ant", "config.json"),
                os.path.join(".config", "anthropic", "credentials.json")):
        if os.path.exists(os.path.join(home, rel)):
            return True
    return False


class Usage(object):
    """Running total of billed tokens, so the run reports what it SPENT rather
    than what it estimated."""

    def __init__(self):
        self.input = 0
        self.output = 0
        self.cache_write = 0
        self.cache_read = 0
        self.requests = 0

    def add(self, usage):
        if usage is None:
            return
        self.requests += 1
        self.input += getattr(usage, "input_tokens", 0) or 0
        self.output += getattr(usage, "output_tokens", 0) or 0
        self.cache_write += getattr(usage, "cache_creation_input_tokens", 0) or 0
        self.cache_read += getattr(usage, "cache_read_input_tokens", 0) or 0

    @property
    def cache_hit_rate(self):
        d = self.cache_read + self.cache_write
        return (self.cache_read / float(d)) if d else 0.0

    def cost(self, model, batch=True, ttl="5m"):
        """Bill cache writes at the TTL the run actually used.

        Charging a 5m run at the 1h write rate overstates the bill by 60% on
        the cache-write column, which on a batch is the largest column."""
        from .requests import price_for
        p = price_for(model)
        mult = 0.5 if batch else 1.0
        cw = p["cw1h"] if ttl == "1h" else p["cw5m"]
        return mult * (
            self.input / 1e6 * p["in"]
            + self.output / 1e6 * p["out"]
            + self.cache_write / 1e6 * cw
            + self.cache_read / 1e6 * p["cr"]
        )

    def report(self, model, batch=True, ttl="5m"):
        out = []
        out.append("  requests            : %d" % self.requests)
        out.append("  uncached input      : %d tok" % self.input)
        out.append("  cache writes        : %d tok" % self.cache_write)
        out.append("  cache reads         : %d tok" % self.cache_read)
        out.append("  output              : %d tok" % self.output)
        out.append("  cache hit rate      : %.1f%%" % (100 * self.cache_hit_rate))
        out.append("  approx cost         : $%.2f  (%s rates%s)"
                   % (self.cost(model, batch, ttl), model,
                      ", batch 50% off" if batch else ""))
        breakeven = 0.53 if ttl == "1h" else 0.22
        if self.requests >= 20 and self.cache_hit_rate < 0.05:
            out.append("  !! cache hit rate below 5%: the cached prefix is not "
                       "byte-stable, so the design is doing nothing while "
                       "still billing the write multiplier.")
        elif self.requests >= 20 and self.cache_hit_rate < breakeven:
            out.append("  !  %.0f%% is below the %.0f%% break-even for a %s TTL "
                       "- caching cost slightly MORE here than sending the "
                       "prefix uncached would have. Not a broken prefix, just "
                       "a batch behaving normally."
                       % (100 * self.cache_hit_rate, 100 * breakeven, ttl))
        return "\n".join(out)
