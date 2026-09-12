"""Dependency-free core DBC parser and deterministic writer for OBD Atlas.

The implementation intentionally supports the evidence-bearing DBC constructs
Atlas can round-trip without guessing: nodes, messages, signals, comments, and
signal value descriptions. Unknown statements are retained as passthrough lines
so importing and exporting does not silently discard vendor extensions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


class DbcError(ValueError):
    pass


@dataclass(frozen=True)
class DbcValue:
    value: int
    text: str


@dataclass
class DbcSignal:
    name: str
    start_bit: int
    length: int
    byte_order: int
    is_signed: bool
    factor: float
    offset: float
    minimum: float
    maximum: float
    unit: str
    receivers: list[str]
    multiplex: str | None = None
    comment: str | None = None
    values: list[DbcValue] = field(default_factory=list)


@dataclass
class DbcMessage:
    arbitration_id: int
    is_extended: bool
    name: str
    dlc: int
    transmitter: str
    signals: list[DbcSignal] = field(default_factory=list)
    comment: str | None = None


@dataclass
class DbcDatabase:
    version: str = ""
    nodes: list[str] = field(default_factory=list)
    messages: list[DbcMessage] = field(default_factory=list)
    passthrough: list[str] = field(default_factory=list)


MESSAGE_RE = re.compile(r"^BO_\s+(\d+)\s+([A-Za-z_][\w]*)\s*:\s*(\d+)\s+(\S+)\s*$")
SIGNAL_RE = re.compile(
    r'^SG_\s+([A-Za-z_][\w]*)\s*(?:(M|m\d+(?:M)?))?\s*:\s*'
    r'(\d+)\|(\d+)@([01])([+-])\s*'
    r'\(([-+0-9.eE]+),([-+0-9.eE]+)\)\s*'
    r'\[([-+0-9.eE]+)\|([-+0-9.eE]+)\]\s*'
    r'"((?:[^"\\]|\\.)*)"\s*(.*)$'
)
VALUE_RE = re.compile(r"^VAL_\s+(\d+)\s+([A-Za-z_][\w]*)\s+(.*);\s*$")
VALUE_PAIR_RE = re.compile(r'(-?\d+)\s+"((?:[^"\\]|\\.)*)"')
MESSAGE_COMMENT_RE = re.compile(r'^CM_\s+BO_\s+(\d+)\s+"((?:[^"\\]|\\.)*)"\s*;\s*$')
SIGNAL_COMMENT_RE = re.compile(
    r'^CM_\s+SG_\s+(\d+)\s+([A-Za-z_][\w]*)\s+"((?:[^"\\]|\\.)*)"\s*;\s*$'
)
VERSION_RE = re.compile(r'^VERSION\s+"((?:[^"\\]|\\.)*)"\s*$')


def unescape(text: str) -> str:
    return text.replace(r"\"", '"').replace(r"\\", "\\")


def escape(text: str) -> str:
    return text.replace("\\", r"\\").replace('"', r'\"')


def decode_dbc_id(raw_id: int) -> tuple[int, bool]:
    if raw_id < 0 or raw_id > 0xFFFFFFFF:
        raise DbcError(f"DBC message ID outside 32-bit range: {raw_id}")
    if raw_id & 0x80000000:
        arbitration_id = raw_id & 0x1FFFFFFF
        return arbitration_id, True
    if raw_id > 0x7FF:
        # Some tools emit an unflagged 29-bit value. Retain it as extended.
        if raw_id > 0x1FFFFFFF:
            raise DbcError(f"Invalid 29-bit CAN ID: {raw_id}")
        return raw_id, True
    return raw_id, False


def encode_dbc_id(arbitration_id: int, is_extended: bool) -> int:
    maximum = 0x1FFFFFFF if is_extended else 0x7FF
    if arbitration_id < 0 or arbitration_id > maximum:
        kind = "extended" if is_extended else "standard"
        raise DbcError(f"Invalid {kind} CAN ID: {arbitration_id:#x}")
    return arbitration_id | (0x80000000 if is_extended else 0)


def message_lookup(database: DbcDatabase) -> dict[int, DbcMessage]:
    return {encode_dbc_id(m.arbitration_id, m.is_extended): m for m in database.messages}


def parse_dbc_text(text: str) -> DbcDatabase:
    database = DbcDatabase()
    current: DbcMessage | None = None
    pending_values: list[tuple[int, str, list[DbcValue]]] = []
    pending_message_comments: list[tuple[int, str]] = []
    pending_signal_comments: list[tuple[int, str, str]] = []
    in_names = False

    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        version = VERSION_RE.match(line)
        if version:
            database.version = unescape(version.group(1))
            continue
        if line.startswith("NS_"):
            in_names = True
            continue
        if in_names:
            if line.startswith("BS_"):
                in_names = False
            else:
                continue
        if line.startswith("BS_"):
            continue
        if line.startswith("BU_:"):
            database.nodes.extend(node for node in line[4:].strip().split() if node)
            continue

        match = MESSAGE_RE.match(line)
        if match:
            raw_id = int(match.group(1))
            arbitration_id, is_extended = decode_dbc_id(raw_id)
            dlc = int(match.group(3))
            if dlc < 0 or dlc > 64:
                raise DbcError(f"Line {line_number}: DLC outside 0..64")
            current = DbcMessage(
                arbitration_id, is_extended, match.group(2), dlc, match.group(4)
            )
            database.messages.append(current)
            continue

        match = SIGNAL_RE.match(line)
        if match:
            if current is None:
                raise DbcError(f"Line {line_number}: signal has no preceding message")
            receivers = [item.strip() for item in match.group(12).split(",") if item.strip()]
            signal = DbcSignal(
                name=match.group(1), multiplex=match.group(2),
                start_bit=int(match.group(3)), length=int(match.group(4)),
                byte_order=int(match.group(5)), is_signed=match.group(6) == "-",
                factor=float(match.group(7)), offset=float(match.group(8)),
                minimum=float(match.group(9)), maximum=float(match.group(10)),
                unit=unescape(match.group(11)), receivers=receivers,
            )
            if signal.length < 1 or signal.length > 64:
                raise DbcError(f"Line {line_number}: signal length outside 1..64")
            if signal.start_bit < 0 or signal.start_bit >= current.dlc * 8:
                raise DbcError(f"Line {line_number}: signal start bit outside message")
            current.signals.append(signal)
            continue

        match = VALUE_RE.match(line)
        if match:
            values = [DbcValue(int(v), unescape(t)) for v, t in VALUE_PAIR_RE.findall(match.group(3))]
            if not values and match.group(3).strip():
                raise DbcError(f"Line {line_number}: malformed VAL_ statement")
            pending_values.append((int(match.group(1)), match.group(2), values))
            continue
        match = MESSAGE_COMMENT_RE.match(line)
        if match:
            pending_message_comments.append((int(match.group(1)), unescape(match.group(2))))
            continue
        match = SIGNAL_COMMENT_RE.match(line)
        if match:
            pending_signal_comments.append(
                (int(match.group(1)), match.group(2), unescape(match.group(3)))
            )
            continue
        if line.startswith(("BA_", "BA_DEF_", "BA_DEF_DEF_", "SIG_GROUP_", "SIG_VALTYPE_", "BO_TX_BU_")):
            database.passthrough.append(line)
            continue
        # Preserve unknown vendor extensions, but reject malformed core statements.
        if line.startswith(("BO_", "SG_", "VAL_", "CM_")):
            raise DbcError(f"Line {line_number}: malformed DBC statement: {line[:120]}")
        database.passthrough.append(line)

    lookup = message_lookup(database)
    if len(lookup) != len(database.messages):
        raise DbcError("DBC contains duplicate message identifiers")
    for raw_id, signal_name, values in pending_values:
        decoded_id, decoded_extended = decode_dbc_id(raw_id)
        message = lookup.get(encode_dbc_id(decoded_id, decoded_extended))
        signal = next((s for s in message.signals if s.name == signal_name), None) if message else None
        if signal is None:
            raise DbcError(f"VAL_ references missing signal {raw_id} {signal_name}")
        signal.values = values
    for raw_id, comment in pending_message_comments:
        decoded_id, decoded_extended = decode_dbc_id(raw_id)
        message = lookup.get(encode_dbc_id(decoded_id, decoded_extended))
        if message is None:
            raise DbcError(f"CM_ references missing message {raw_id}")
        message.comment = comment
    for raw_id, signal_name, comment in pending_signal_comments:
        decoded_id, decoded_extended = decode_dbc_id(raw_id)
        message = lookup.get(encode_dbc_id(decoded_id, decoded_extended))
        signal = next((s for s in message.signals if s.name == signal_name), None) if message else None
        if signal is None:
            raise DbcError(f"CM_ references missing signal {raw_id} {signal_name}")
        signal.comment = comment
    return database


def parse_dbc(path: Path) -> DbcDatabase:
    try:
        return parse_dbc_text(path.read_text(encoding="utf-8-sig"))
    except UnicodeDecodeError as exc:
        raise DbcError(f"DBC is not valid UTF-8: {exc}") from exc


def number(value: float) -> str:
    if value == int(value):
        return str(int(value))
    return format(value, ".15g")


def write_dbc(database: DbcDatabase) -> str:
    lines = [f'VERSION "{escape(database.version)}"', "", "NS_ :", "", "BS_:", ""]
    lines.append("BU_: " + " ".join(database.nodes))
    lines.append("")
    for message in database.messages:
        raw_id = encode_dbc_id(message.arbitration_id, message.is_extended)
        lines.append(f"BO_ {raw_id} {message.name}: {message.dlc} {message.transmitter}")
        for signal in message.signals:
            mux = f" {signal.multiplex}" if signal.multiplex else ""
            sign = "-" if signal.is_signed else "+"
            receivers = ",".join(signal.receivers) or "Vector__XXX"
            lines.append(
                f" SG_ {signal.name}{mux} : {signal.start_bit}|{signal.length}@"
                f"{signal.byte_order}{sign} ({number(signal.factor)},{number(signal.offset)}) "
                f"[{number(signal.minimum)}|{number(signal.maximum)}] "
                f'"{escape(signal.unit)}" {receivers}'
            )
        lines.append("")
    for message in database.messages:
        raw_id = encode_dbc_id(message.arbitration_id, message.is_extended)
        if message.comment is not None:
            lines.append(f'CM_ BO_ {raw_id} "{escape(message.comment)}";')
        for signal in message.signals:
            if signal.comment is not None:
                lines.append(f'CM_ SG_ {raw_id} {signal.name} "{escape(signal.comment)}";')
            if signal.values:
                pairs = " ".join(f'{item.value} "{escape(item.text)}"' for item in signal.values)
                lines.append(f"VAL_ {raw_id} {signal.name} {pairs} ;")
    if database.passthrough:
        lines.extend(["", *database.passthrough])
    return "\n".join(lines).rstrip() + "\n"


def semantic_model(database: DbcDatabase) -> tuple:
    return (
        database.version,
        tuple(database.nodes),
        tuple(
            (
                m.arbitration_id, m.is_extended, m.name, m.dlc, m.transmitter, m.comment,
                tuple(
                    (
                        s.name, s.start_bit, s.length, s.byte_order, s.is_signed,
                        s.factor, s.offset, s.minimum, s.maximum, s.unit,
                        tuple(s.receivers), s.multiplex, s.comment,
                        tuple((v.value, v.text) for v in s.values),
                    )
                    for s in m.signals
                ),
            )
            for m in database.messages
        ),
    )


def assert_round_trip(database: DbcDatabase, rendered: str) -> None:
    reparsed = parse_dbc_text(rendered)
    if semantic_model(database) != semantic_model(reparsed):
        raise DbcError("Generated DBC failed semantic round-trip validation")
