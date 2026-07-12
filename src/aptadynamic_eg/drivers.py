"""Causal-availability registry for electrical-grid observation drivers."""

DRIVER_SPECS = {
    "intensity": {
        "causal": True,
        "note": "outage-start counts; knowable at t",
    },
    "load": {
        "causal": "conditional",
        "note": (
            "active-outage count; causal in content but requires a declared "
            "real-time availability contract before confirmatory use"
        ),
    },
    "severity": {
        "causal": False,
        "note": (
            "voltage-weighted log duration placed at the START bin; duration "
            "is known only at restoration — future information"
        ),
    },
}


def driver_spec(name: str) -> dict:
    """Return a registered driver specification or reject unknown drivers."""

    try:
        return DRIVER_SPECS[name]
    except KeyError as exc:
        raise ValueError(
            f"driver {name!r} is not registered in the electrical O_D layer"
        ) from exc
