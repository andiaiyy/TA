"""
Dataset schema definitions.

Each schema defines the expected columns for a dataset type.
Used by validator.py to check uploaded CSVs.

⚠️  CICIDS2017 CSVs have leading whitespace in column headers.
    These are the POST-STRIP names (parser strips whitespace before validation).
"""

CICIDS2017_SCHEMA = {
    "label_column": "Label",
    "expected_columns": [
        "Destination Port", "Flow Duration", "Total Fwd Packets",
        "Total Backward Packets", "Total Length of Fwd Packets",
        "Total Length of Bwd Packets", "Fwd Packet Length Max",
        "Fwd Packet Length Min", "Fwd Packet Length Mean",
        "Fwd Packet Length Std", "Bwd Packet Length Max",
        "Bwd Packet Length Min", "Bwd Packet Length Mean",
        "Bwd Packet Length Std", "Flow Bytes/s", "Flow Packets/s",
        "Flow IAT Mean", "Flow IAT Std", "Flow IAT Max", "Flow IAT Min",
        "Fwd IAT Total", "Fwd IAT Mean", "Fwd IAT Std", "Fwd IAT Max",
        "Fwd IAT Min", "Bwd IAT Total", "Bwd IAT Mean", "Bwd IAT Std",
        "Bwd IAT Max", "Bwd IAT Min", "Fwd PSH Flags", "Bwd PSH Flags",
        "Fwd URG Flags", "Bwd URG Flags", "Fwd Header Length",
        "Bwd Header Length", "Fwd Packets/s", "Bwd Packets/s",
        "Min Packet Length", "Max Packet Length", "Packet Length Mean",
        "Packet Length Std", "Packet Length Variance", "FIN Flag Count",
        "SYN Flag Count", "RST Flag Count", "PSH Flag Count",
        "ACK Flag Count", "URG Flag Count", "CWE Flag Count",
        "ECE Flag Count", "Down/Up Ratio", "Average Packet Size",
        "Avg Fwd Segment Size", "Avg Bwd Segment Size",
        "Fwd Header Length.1", "Fwd Avg Bytes/Bulk",
        "Fwd Avg Packets/Bulk", "Fwd Avg Bulk Rate",
        "Bwd Avg Bytes/Bulk", "Bwd Avg Packets/Bulk",
        "Bwd Avg Bulk Rate", "Subflow Fwd Packets", "Subflow Fwd Bytes",
        "Subflow Bwd Packets", "Subflow Bwd Bytes",
        "Init_Win_bytes_forward", "Init_Win_bytes_backward",
        "act_data_pkt_fwd", "min_seg_size_forward", "Active Mean",
        "Active Std", "Active Max", "Active Min", "Idle Mean",
        "Idle Std", "Idle Max", "Idle Min", "Label"
    ]
}

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

DATASET_SCHEMAS = {
    "CICIDS2017": CICIDS2017_SCHEMA,
    "HIKARI2021": HIKARI2021_SCHEMA,
}


def get_schema(dataset_type: str) -> dict | None:
    """Return schema for a dataset type, or None if unknown."""
    return DATASET_SCHEMAS.get(dataset_type)


def supported_datasets() -> list[str]:
    """Return list of supported dataset type names."""
    return list(DATASET_SCHEMAS.keys())