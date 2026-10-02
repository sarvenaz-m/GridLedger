// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

/// @title PredictionRegistry
/// @notice Anchors off-chain prediction and manifest digests. Does not validate ML truth.
/// @dev Local research prototype; governance, multisig and production audit are out of scope.
contract PredictionRegistry {
    address public immutable owner;
    mapping(address => bool) public writers;
    struct Anchor { bytes32 digest; bytes32 manifest; address writer; uint256 timestamp; }
    mapping(bytes32 => Anchor) public anchors;
    uint256 public count;
    event WriterChanged(address indexed account, bool enabled);
    event Anchored(bytes32 indexed id, bytes32 digest, bytes32 manifest, address indexed writer);
    error Unauthorized();
    error InvalidInput();
    error AlreadyAnchored();

    constructor() { owner = msg.sender; writers[msg.sender] = true; }
    function setWriter(address account, bool enabled) external {
        if (msg.sender != owner) revert Unauthorized();
        if (account == address(0)) revert InvalidInput();
        writers[account] = enabled;
        emit WriterChanged(account, enabled);
    }
    function anchor(bytes32 id, bytes32 recordDigest, bytes32 manifestDigest) external {
        if (!writers[msg.sender]) revert Unauthorized();
        if (id == bytes32(0) || recordDigest == bytes32(0) || manifestDigest == bytes32(0)) revert InvalidInput();
        if (anchors[id].writer != address(0)) revert AlreadyAnchored();
        anchors[id] = Anchor(recordDigest, manifestDigest, msg.sender, block.timestamp);
        count += 1;
        emit Anchored(id, recordDigest, manifestDigest, msg.sender);
    }
}
