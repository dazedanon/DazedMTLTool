#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
client.py - Anthropic client construction and token accounting.

An unset ANTHROPIC_API_KEY does NOT mean there are no credentials: the SDK
resolves ANTHROPIC_API_KEY -> ANTHROPIC_AUTH_TOKEN -> the profile written by
`ant auth login` -> Workload Identity Federation. So the zero-argument
constructor is the right call, and the error points at `ant auth status`
rather than demanding a key.
"""

import sys


def get_client():
    try:
        from anthropic import Anthropic
    except ImportError:
        sys.exit("ERROR: pip install anthropic")
    try:
        return Anthropic()
    except Exception as e:
        sys.exit(
            "ERROR: could not construct an Anthropic client (%s).\n"
            "  Credentials resolve in this order: ANTHROPIC_API_KEY, "
            "ANTHROPIC_AUTH_TOKEN, an `ant auth login` profile, WIF.\n"
            "  Run `ant auth status` to see which one is active." % e)


class Usage(object):
    """Running total of BILLED tokens, so a run reports what it spent rather
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

    def cost(self, model, batch=True, ttl="1h"):
        """`ttl` selects the cache-WRITE rate actually paid: 2.00x base input
        at 1h, 1.25x at 5m. The batch driver writes at 1h and the live driver
        at 5m, so hard-coding either one misreports the other by 60%."""
        from .requests import price_for
        p = price_for(model)
        mult = 0.5 if batch else 1.0
        write_rate = p["cw1h"] if ttl == "1h" else p["cw5m"]
        return mult * (
            self.input / 1e6 * p["in"]
            + self.output / 1e6 * p["out"]
            + self.cache_write / 1e6 * write_rate
            + self.cache_read / 1e6 * p["cr"]
        )

    def report(self, model, batch=True, ttl=None):
        ttl = ttl or ("1h" if batch else "5m")
        out = ["  requests            : %d" % self.requests,
               "  uncached input      : %d tok" % self.input,
               "  cache writes        : %d tok  (%s ttl)" % (self.cache_write, ttl),
               "  cache reads         : %d tok" % self.cache_read,
               "  output              : %d tok" % self.output,
               "  cache hit rate      : %.1f%%" % (100 * self.cache_hit_rate),
               "  approx cost         : $%.2f  (%s rates%s)"
               % (self.cost(model, batch, ttl), model,
                  ", batch 50% off" if batch else "")]
        if self.requests >= 20 and self.cache_hit_rate < 0.05:
            out.append("  !! cache hit rate below 5%: the cached prefix is not "
                       "byte-stable, so the design is doing nothing while "
                       "still billing the write multiplier.")
        return "\n".join(out)
