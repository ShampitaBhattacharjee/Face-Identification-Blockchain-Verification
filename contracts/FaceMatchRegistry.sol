// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/// @title FaceMatchRegistry
/// @notice Append-only, tamper-evident registry linking a photo hash and a face-embedding
///         hash to a publicly discoverable social-media post found via reverse-image search.
/// @dev Records can never be edited or deleted. Anyone can verify a record by recomputing
///      the SHA-256 of the original image and comparing it with `imageHash`.
contract FaceMatchRegistry {
    struct Record {
        bytes32 imageHash;     // SHA-256 of the original image bytes
        bytes32 embeddingHash; // SHA-256 of the rounded face-embedding vector
        string postUrl;        // Matching social-media post URL
        string provider;       // Reverse-image search provider that produced the match
        uint256 timestamp;     // Block timestamp at anchoring time
        address submitter;     // Wallet that anchored the record
    }

    Record[] private _records;
    mapping(bytes32 => uint256[]) private _recordsByImageHash;

    event MatchRecorded(
        uint256 indexed id,
        bytes32 indexed imageHash,
        bytes32 embeddingHash,
        string postUrl,
        string provider,
        uint256 timestamp,
        address indexed submitter
    );

    error EmptyUrl();
    error RecordNotFound(uint256 id);

    /// @notice Anchor a new face/post match. Emits `MatchRecorded`.
    /// @return id Sequential identifier of the stored record.
    function recordMatch(
        bytes32 imageHash,
        bytes32 embeddingHash,
        string calldata postUrl,
        string calldata provider
    ) external returns (uint256 id) {
        if (bytes(postUrl).length == 0) revert EmptyUrl();
        id = _records.length;
        _records.push(
            Record({
                imageHash: imageHash,
                embeddingHash: embeddingHash,
                postUrl: postUrl,
                provider: provider,
                timestamp: block.timestamp,
                submitter: msg.sender
            })
        );
        _recordsByImageHash[imageHash].push(id);
        emit MatchRecorded(id, imageHash, embeddingHash, postUrl, provider, block.timestamp, msg.sender);
    }

    function getRecord(uint256 id) external view returns (Record memory) {
        if (id >= _records.length) revert RecordNotFound(id);
        return _records[id];
    }

    function recordCount() external view returns (uint256) {
        return _records.length;
    }

    function recordsByImageHash(bytes32 imageHash) external view returns (uint256[] memory) {
        return _recordsByImageHash[imageHash];
    }
}
