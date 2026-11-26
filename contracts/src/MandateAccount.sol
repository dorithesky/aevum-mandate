// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

/// @title MandateAccount
/// @notice A stablecoin payment account whose spending rules live on chain.
///         The owner keeps custody and policy control; an AI agent may only
///         settle invoices inside the mandate: verified payees, caps, expiry,
///         one-shot invoice ids, and an owner co-signature above a threshold.
///         The account holds no owner key and the agent can never withdraw.
/// @dev Deployed against tUSD8 on QDay Aevum testnet (chain id 44005).
interface IERC20 {
    function transfer(address to, uint256 amount) external returns (bool);
    function balanceOf(address account) external view returns (uint256);
}

contract MandateAccount {
    /* ------------------------------------------------------------------ */
    /*                              Types                                 */
    /* ------------------------------------------------------------------ */

    struct Beneficiary {
        bytes32 nameHash; // keccak256 of the verified legal/trading name
        address wallet; // the only address this payee may be paid at
        address signer; // key that signs this payee's invoices (may be 0)
        bool active;
    }

    struct Payment {
        bytes32 invoiceId; // unique id, consumed once
        uint256 beneficiaryId;
        address payee; // as printed on the invoice
        bytes32 payeeNameHash; // keccak256 of the name printed on the invoice
        uint256 amount; // in token decimals
        bytes32 memoHash; // hash of the invoice body / reference
        uint256 dueDate;
        uint256 validUntil; // settlement deadline
        uint256 nonce; // approval nonce (owner co-signature)
    }

    /* ------------------------------------------------------------------ */
    /*                          Refusal codes                             */
    /* ------------------------------------------------------------------ */

    uint8 public constant OK = 0;
    uint8 public constant REFUSED_PAUSED = 1;
    uint8 public constant REFUSED_POLICY_EXPIRED = 2;
    uint8 public constant REFUSED_UNKNOWN_PAYEE = 3;
    uint8 public constant REFUSED_PAYEE_INACTIVE = 4;
    uint8 public constant REFUSED_NAME_MISMATCH = 5;
    uint8 public constant REFUSED_ADDRESS_MISMATCH = 6;
    uint8 public constant REFUSED_DUPLICATE_INVOICE = 7;
    uint8 public constant REFUSED_ZERO_AMOUNT = 8;
    uint8 public constant REFUSED_OVER_PER_PAYMENT_CAP = 9;
    uint8 public constant REFUSED_OVER_DAILY_CAP = 10;
    uint8 public constant REFUSED_APPROVAL_REQUIRED = 11;
    uint8 public constant REFUSED_INVALID_APPROVAL = 12;
    uint8 public constant REFUSED_INSUFFICIENT_BALANCE = 13;
    uint8 public constant REFUSED_NOT_AGENT = 14;
    // Codes 15+ are used by the agent off chain (invoice signature, expiry,
    // malformed invoice). They are recorded here too so the audit trail is uniform.
    uint8 public constant REFUSED_INVOICE_SIGNATURE = 15;
    uint8 public constant REFUSED_INVOICE_EXPIRED = 16;
    uint8 public constant REFUSED_MALFORMED_INVOICE = 17;

    /* ------------------------------------------------------------------ */
    /*                              Storage                               */
    /* ------------------------------------------------------------------ */

    bytes32 private constant DOMAIN_TYPEHASH =
        keccak256("EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)");
    bytes32 private constant APPROVAL_TYPEHASH = keccak256(
        "Approval(bytes32 invoiceId,uint256 beneficiaryId,address payee,uint256 amount,uint256 validUntil,uint256 nonce)"
    );

    IERC20 public immutable token;
    address public owner;
    address public agent;
    bool public paused;

    uint256 public perPaymentCap;
    uint256 public dailyCap;
    uint256 public approvalThreshold; // amount above this needs the owner's signature
    uint256 public policyExpiry; // 0 = no expiry

    uint256 public spentToday;
    uint256 public spendDay;

    uint256 public beneficiaryCount;
    mapping(uint256 => Beneficiary) private _beneficiaries;

    mapping(bytes32 => bool) public invoiceUsed;
    mapping(uint256 => bool) public approvalNonceUsed;

    /* ------------------------------------------------------------------ */
    /*                              Events                                */
    /* ------------------------------------------------------------------ */

    event PaymentSettled(
        bytes32 indexed invoiceId,
        uint256 indexed beneficiaryId,
        address indexed payee,
        uint256 amount,
        bool approvedByOwner,
        bytes32 memoHash,
        uint256 dueDate
    );
    event RefusalRecorded(
        bytes32 indexed invoiceId,
        address indexed agent,
        uint8 reason,
        uint256 amount,
        bytes32 payeeNameHash
    );
    event BeneficiaryAdded(uint256 indexed id, bytes32 nameHash, address wallet, address signer);
    event BeneficiaryStatusChanged(uint256 indexed id, bool active);
    event AgentChanged(address indexed previousAgent, address indexed newAgent);
    event PolicyChanged(uint256 perPaymentCap, uint256 dailyCap, uint256 approvalThreshold, uint256 policyExpiry);
    event Paused(bool paused);
    event OwnerChanged(address indexed previousOwner, address indexed newOwner);
    event Withdrawn(address indexed to, uint256 amount);

    /* ------------------------------------------------------------------ */
    /*                              Errors                                */
    /* ------------------------------------------------------------------ */

    error Refused(uint8 code);
    error NotOwner();
    error NotAgent();
    error NotPendingOwner();
    error TransferFailed();

    /* ------------------------------------------------------------------ */
    /*                            Constructor                             */
    /* ------------------------------------------------------------------ */

    constructor(IERC20 token_, address owner_) {
        require(address(token_) != address(0), "token");
        require(owner_ != address(0), "owner");
        token = token_;
        owner = owner_;
        emit OwnerChanged(address(0), owner_);
    }

    modifier onlyOwner() {
        if (msg.sender != owner) revert NotOwner();
        _;
    }

    modifier onlyAgent() {
        if (msg.sender != agent) revert NotAgent();
        _;
    }

    /* ------------------------------------------------------------------ */
    /*                          Owner: policy                             */
    /* ------------------------------------------------------------------ */

    function setPolicy(uint256 perPaymentCap_, uint256 dailyCap_, uint256 approvalThreshold_, uint256 policyExpiry_)
        external
        onlyOwner
    {
        require(perPaymentCap_ > 0 && dailyCap_ > 0, "caps");
        require(approvalThreshold_ <= perPaymentCap_, "threshold above cap");
        perPaymentCap = perPaymentCap_;
        dailyCap = dailyCap_;
        approvalThreshold = approvalThreshold_;
        policyExpiry = policyExpiry_;
        emit PolicyChanged(perPaymentCap_, dailyCap_, approvalThreshold_, policyExpiry_);
    }

    function setAgent(address newAgent) external onlyOwner {
        emit AgentChanged(agent, newAgent);
        agent = newAgent;
    }

    function setPaused(bool value) external onlyOwner {
        paused = value;
        emit Paused(value);
    }

    function addBeneficiary(bytes32 nameHash, address wallet, address signer) external onlyOwner returns (uint256 id) {
        require(nameHash != bytes32(0), "name");
        require(wallet != address(0), "wallet");
        beneficiaryCount += 1;
        id = beneficiaryCount;
        _beneficiaries[id] = Beneficiary({nameHash: nameHash, wallet: wallet, signer: signer, active: true});
        emit BeneficiaryAdded(id, nameHash, wallet, signer);
    }

    function setBeneficiaryActive(uint256 id, bool active) external onlyOwner {
        require(_beneficiaries[id].wallet != address(0), "unknown");
        _beneficiaries[id].active = active;
        emit BeneficiaryStatusChanged(id, active);
    }

    /// @notice Owner can always take the money back. The agent cannot.
    function withdraw(address to, uint256 amount) external onlyOwner {
        require(to != address(0), "to");
        _safeTransfer(to, amount);
        emit Withdrawn(to, amount);
    }

    function transferOwnership(address newOwner) external onlyOwner {
        require(newOwner != address(0), "owner");
        emit OwnerChanged(owner, newOwner);
        owner = newOwner;
    }

    // Two-step ownership is not needed for the demo; a production deployment
    // should add a pending-owner handshake (see docs/SECURITY.md).

    /* ------------------------------------------------------------------ */
    /*                          Agent: payment                            */
    /* ------------------------------------------------------------------ */

    /// @notice The agent settles one invoice. Reverts with Refused(code) when
    ///         the mandate does not allow it; nothing moves on a refusal.
    function pay(Payment calldata p, bytes calldata approval) external onlyAgent returns (uint8) {
        uint8 code = _check(p, approval);
        if (code != OK) revert Refused(code);

        bool approved = approval.length > 0;
        invoiceUsed[p.invoiceId] = true;
        if (approved) approvalNonceUsed[p.nonce] = true;
        _bookSpend(p.amount);
        _safeTransfer(p.payee, p.amount);

        emit PaymentSettled(
            p.invoiceId, p.beneficiaryId, p.payee, p.amount, approved, p.memoHash, p.dueDate
        );
        return OK;
    }

    /// @notice On-chain record of a payment the agent declined before sending
    ///         money, so refusals are as auditable as settlements.
    function recordRefusal(bytes32 invoiceId, uint8 reason, uint256 amount, bytes32 payeeNameHash)
        external
        onlyAgent
    {
        require(reason != OK, "reason");
        emit RefusalRecorded(invoiceId, msg.sender, reason, amount, payeeNameHash);
    }

    /* ------------------------------------------------------------------ */
    /*                              Views                                 */
    /* ------------------------------------------------------------------ */

    function preview(Payment calldata p, bytes calldata approval) external view returns (uint8) {
        return _check(p, approval);
    }

    function getBeneficiary(uint256 id) external view returns (Beneficiary memory) {
        return _beneficiaries[id];
    }

    function remainingToday() public view returns (uint256) {
        if (spendDay != _today()) return dailyCap;
        if (spentToday >= dailyCap) return 0;
        return dailyCap - spentToday;
    }

    function domainSeparator() public view returns (bytes32) {
        return keccak256(
            abi.encode(DOMAIN_TYPEHASH, keccak256(bytes("Aevum Mandate")), keccak256(bytes("1")), block.chainid, address(this))
        );
    }

    /// @notice Digest the owner signs (EIP-712) to approve one above-threshold payment.
    function approvalDigest(bytes32 invoiceId, uint256 beneficiaryId, address payee, uint256 amount, uint256 validUntil, uint256 nonce)
        public
        view
        returns (bytes32)
    {
        bytes32 structHash =
            keccak256(abi.encode(APPROVAL_TYPEHASH, invoiceId, beneficiaryId, payee, amount, validUntil, nonce));
        return keccak256(abi.encodePacked("\x19\x01", domainSeparator(), structHash));
    }

    /* ------------------------------------------------------------------ */
    /*                            Internals                               */
    /* ------------------------------------------------------------------ */

    function _check(Payment calldata p, bytes calldata approval) private view returns (uint8) {
        if (paused) return REFUSED_PAUSED;
        if (policyExpiry != 0 && block.timestamp > policyExpiry) return REFUSED_POLICY_EXPIRED;

        Beneficiary storage b = _beneficiaries[p.beneficiaryId];
        if (b.wallet == address(0)) return REFUSED_UNKNOWN_PAYEE;
        if (!b.active) return REFUSED_PAYEE_INACTIVE;
        if (p.payeeNameHash != b.nameHash) return REFUSED_NAME_MISMATCH;
        if (p.payee != b.wallet) return REFUSED_ADDRESS_MISMATCH;
        if (invoiceUsed[p.invoiceId]) return REFUSED_DUPLICATE_INVOICE;
        if (p.amount == 0) return REFUSED_ZERO_AMOUNT;
        if (p.amount > perPaymentCap) return REFUSED_OVER_PER_PAYMENT_CAP;
        if (p.validUntil != 0 && block.timestamp > p.validUntil) return REFUSED_INVOICE_EXPIRED;

        uint256 spent = spendDay == _today() ? spentToday : 0;
        if (spent + p.amount > dailyCap) return REFUSED_OVER_DAILY_CAP;

        if (p.amount > approvalThreshold) {
            if (approval.length == 0) return REFUSED_APPROVAL_REQUIRED;
            if (!_validApproval(p, approval)) return REFUSED_INVALID_APPROVAL;
        }

        if (token.balanceOf(address(this)) < p.amount) return REFUSED_INSUFFICIENT_BALANCE;
        return OK;
    }

    function _validApproval(Payment calldata p, bytes calldata approval) private view returns (bool) {
        if (approval.length != 65) return false;
        if (approvalNonceUsed[p.nonce]) return false;
        bytes32 digest = approvalDigest(p.invoiceId, p.beneficiaryId, p.payee, p.amount, p.validUntil, p.nonce);
        bytes32 r;
        bytes32 s;
        uint8 v;
        assembly {
            r := calldataload(approval.offset)
            s := calldataload(add(approval.offset, 32))
            v := byte(0, calldataload(add(approval.offset, 64)))
        }
        if (v < 27) v += 27;
        if (v != 27 && v != 28) return false;
        address signer = ecrecover(digest, v, r, s);
        return signer != address(0) && signer == owner;
    }

    function _bookSpend(uint256 amount) private {
        uint256 today = _today();
        if (spendDay != today) {
            spendDay = today;
            spentToday = amount;
        } else {
            spentToday += amount;
        }
    }

    function _today() private view returns (uint256) {
        return block.timestamp / 1 days;
    }

    function _safeTransfer(address to, uint256 amount) private {
        (bool ok, bytes memory data) = address(token).call(abi.encodeCall(IERC20.transfer, (to, amount)));
        if (!ok || (data.length != 0 && !abi.decode(data, (bool)))) revert TransferFailed();
    }
}
