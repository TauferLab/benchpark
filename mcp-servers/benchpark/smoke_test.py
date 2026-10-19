# Copyright 2023 Lawrence Livermore National Security, LLC and other
# Benchpark Project Developers. See the top-level COPYRIGHT file for details.
#
# SPDX-License-Identifier: Apache-2.0
"""Smoke test: call the read-only tools through an in-process MCP client.

usage: BENCHPARK_PYTHON=/path/to/benchpark/env/python python smoke_test.py [workspace]

Uses no compute and keeps no files. With a workspace path, also checks
status/preview_submission/results on it.
"""

import asyncio
import json
import sys

import server
from mcp import Client


async def call(client, tool, **args):
    res = await client.call_tool(tool, args)
    text = res.content[0].text if res.content else ""
    flag = "ERROR" if res.is_error else "ok"
    print(f"--- {tool}({', '.join(f'{k}={v!r}' for k, v in args.items())}) -> {flag}")
    print(text[:800] + ("..." if len(text) > 800 else ""))
    return res


async def main(workspace=None):
    async with Client(server.mcp) as client:
        tools = await client.list_tools()
        print("tools:", [t.name for t in tools.tools])
        prompts = await client.list_prompts()
        print("prompts:", [p.name for p in prompts.prompts])

        await call(client, "guide", topic="list")
        await call(client, "catalog", kind="experiments")
        await call(client, "describe", kind="experiment", name="saxpy")
        await call(client, "cluster_info")
        await call(
            client,
            "read_file",
            path="experiments/test/saxpy/experiment.py",
            grep="def ",
        )
        ok = await call(
            client,
            "validate_specs",
            system_spec="generic-x86",
            experiment_spec="saxpy +openmp",
        )
        assert not ok.is_error
        bad = await call(
            client,
            "validate_specs",
            system_spec="generic-x86",
            experiment_spec="saxpy +openmp +rocm",
        )
        assert bad.is_error
        if workspace:
            await call(client, "status", workspace=workspace)
            await call(client, "preview_submission", workspace=workspace)
            await call(client, "results", workspace=workspace, analyze=False)
    print(json.dumps({"smoke_test": "passed"}))


if __name__ == "__main__":
    asyncio.run(main(*sys.argv[1:]))
