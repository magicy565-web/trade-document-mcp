"""Export versioned MCP schemas and an installed-runtime CycloneDX SBOM."""

import argparse, asyncio, json
from pathlib import Path
from importlib.metadata import distribution
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from trade_document.server import mcp


def sbom():
    pending = ["trade-document-mcp"]
    components = {}
    dependencies = {}
    while pending:
        name = canonicalize_name(pending.pop())
        if name in components:
            continue
        dist = distribution(name)
        ref = f"pkg:pypi/{name}@{dist.version}"
        components[name] = {
            "type": "library",
            "name": name,
            "version": dist.version,
            "bom-ref": ref,
            "purl": ref,
        }
        depends = []
        for raw in dist.requires or []:
            req = Requirement(raw)
            if req.marker is None or req.marker.evaluate({"extra": ""}):
                pkg = canonicalize_name(req.name)
                depends.append(f"pkg:pypi/{pkg}@{distribution(pkg).version}")
                pending.append(pkg)
        dependencies[ref] = sorted(set(depends))
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "version": 1,
        "components": list(components.values()),
        "dependencies": [{"ref": r, "dependsOn": d} for r, d in dependencies.items()],
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("directory", type=Path)
    dest = p.parse_args().directory
    dest.mkdir(parents=True, exist_ok=True)
    tools = asyncio.run(mcp.list_tools())
    (dest / "mcp-contract.json").write_text(
        json.dumps(
            {
                "api_version": "0.5",
                "tools": [t.model_dump(mode="json", exclude_none=True) for t in tools],
            },
            indent=2,
        )
    )
    (dest / "runtime.cdx.json").write_text(json.dumps(sbom(), indent=2))
    print(f"{len(tools)} tool contracts exported")


if __name__ == "__main__":
    main()
