# Validation notes

Local pre-PR validation of the new passive correlation tool chain covered:

- Python syntax compilation for all new tools;
- normalized internal registry visibility of 96 cell signals and 16 temperature signals;
- candump-compatible SocketCAN frame formatting;
- deterministic synthetic dual-network captures with a deliberately scrambled 96-cell permutation;
- exact recovery of all 96 expected cell-to-slot pairings;
- a three-session agreement gate that yields `repeatableCrossSessionCandidate`, never `confirmed`;
- rejection of a session set when one session disagrees on the assigned slot.

Repository CI is the authoritative validation for the committed tree.
