"""
Dataset schema definitions.

Each schema defines the expected columns for a dataset type.
Used by validator.py to check uploaded CSVs.
"""

HIKARI2021_SCHEMA = {
    "label_column": "Label",
    "expected_columns": [
        "Unnamed: 0.1", "Unnamed: 0", "uid", "originh", "originp", "responh", "responp",
        "flow_duration", "fwd_pkts_tot", "bwd_pkts_tot",
        "fwd_data_pkts_tot", "bwd_data_pkts_tot",
        "fwd_pkts_per_sec", "bwd_pkts_per_sec", "flow_pkts_per_sec",
        "down_up_ratio",
        "fwd_header_size_tot", "fwd_header_size_min", "fwd_header_size_max",
        "bwd_header_size_tot", "bwd_header_size_min", "bwd_header_size_max",
        "flow_FIN_flag_count", "flow_SYN_flag_count", "flow_RST_flag_count",
        "fwd_PSH_flag_count", "bwd_PSH_flag_count", "flow_ACK_flag_count",
        "fwd_URG_flag_count", "bwd_URG_flag_count",
        "flow_CWR_flag_count", "flow_ECE_flag_count",
        "fwd_pkts_payload.min", "fwd_pkts_payload.max",
        "fwd_pkts_payload.tot", "fwd_pkts_payload.avg", "fwd_pkts_payload.std",
        "bwd_pkts_payload.min", "bwd_pkts_payload.max",
        "bwd_pkts_payload.tot", "bwd_pkts_payload.avg", "bwd_pkts_payload.std",
        "flow_pkts_payload.min", "flow_pkts_payload.max",
        "flow_pkts_payload.tot", "flow_pkts_payload.avg", "flow_pkts_payload.std",
        "fwd_iat.min", "fwd_iat.max", "fwd_iat.tot", "fwd_iat.avg", "fwd_iat.std",
        "bwd_iat.min", "bwd_iat.max", "bwd_iat.tot", "bwd_iat.avg", "bwd_iat.std",
        "flow_iat.min", "flow_iat.max", "flow_iat.tot", "flow_iat.avg", "flow_iat.std",
        "payload_bytes_per_second",
        "fwd_subflow_pkts", "bwd_subflow_pkts",
        "fwd_subflow_bytes", "bwd_subflow_bytes",
        "fwd_bulk_bytes", "bwd_bulk_bytes",
        "fwd_bulk_packets", "bwd_bulk_packets",
        "fwd_bulk_rate", "bwd_bulk_rate",
        "active.min", "active.max", "active.tot", "active.avg", "active.std",
        "idle.min", "idle.max", "idle.tot", "idle.avg", "idle.std",
        "fwd_init_window_size", "bwd_init_window_size", "fwd_last_window_size",
        "traffic_category", "Label"
    ]
}

EVE_SURICATA_SCHEMA = {
    "label_column": "Target",
    "file_format": "json_or_csv",
    "expected_top_level_keys": [
        "timestamp", "flow_id", "event_type",
        "src_ip", "src_port", "dest_ip", "dest_port", "proto",
    ],
    "expected_columns": [],
}

DATASET_SCHEMAS = {
    "HIKARI2021": HIKARI2021_SCHEMA,
    "EVE_SURICATA": EVE_SURICATA_SCHEMA,
}


def get_schema(dataset_type: str) -> dict | None:
    """Return schema for a dataset type, or None if unknown."""
    return DATASET_SCHEMAS.get(dataset_type)


def supported_datasets() -> list[str]:
    """Return list of supported dataset type names."""
    return list(DATASET_SCHEMAS.keys())