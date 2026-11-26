// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

import {Test} from "forge-std/Test.sol";
import {MandateAccount, IERC20} from "../src/MandateAccount.sol";

contract MockUSD {
    string public name = "tUSD8";
    uint8 public decimals = 6;
    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;

    function mint(address to, uint256 amount) external {
        balanceOf[to] += amount;
    }

    function transfer(address to, uint256 amount) external returns (bool) {
        require(balanceOf[msg.sender] >= amount, "balance");
        balanceOf[msg.sender] -= amount;
        balanceOf[to] += amount;
        return true;
    }

    function approve(address spender, uint256 amount) external returns (bool) {
        allowance[msg.sender][spender] = amount;
        return true;
    }

    function transferFrom(address from, address to, uint256 amount) external returns (bool) {
        require(balanceOf[from] >= amount, "balance");
        require(allowance[from][msg.sender] >= amount, "allowance");
        allowance[from][msg.sender] -= amount;
        balanceOf[from] -= amount;
        balanceOf[to] += amount;
        return true;
    }
}

contract MandateAccountTest is Test {
    MockUSD token;
    MandateAccount mandate;

    uint256 ownerKey = 0xA11CE;
    address owner;
    address agent = address(0xA9E47);
    address merchantWallet = address(0xB0B);
    address merchantSigner = address(0x51C4);
    address attacker = address(0xBAD);

    bytes32 constant MERCHANT_NAME = keccak256("Acme Studio LLC");
    bytes32 constant ACCOUNTING_NAME = keccak256("Northwind Accounting");
    uint256 merchantId;
    uint256 accountingId;

    uint256 constant PER_TX = 2_000_000; // 2.00
    uint256 constant DAILY = 5_000_000; // 5.00
    uint256 constant THRESHOLD = 2_000_000; // 2.00

    function setUp() public {
        owner = vm.addr(ownerKey);
        token = new MockUSD();
        mandate = new MandateAccount(IERC20(address(token)), owner);

        vm.startPrank(owner);
        mandate.setAgent(agent);
        mandate.setPolicy(PER_TX, DAILY, THRESHOLD, 0);
        merchantId = mandate.addBeneficiary(MERCHANT_NAME, merchantWallet, merchantSigner);
        accountingId = mandate.addBeneficiary(ACCOUNTING_NAME, address(0xC0FFEE), address(0x51C5));
        vm.stopPrank();

        token.mint(address(mandate), 10_000_000); // 10.00 float
    }

    /* ----------------------------- helpers ----------------------------- */

    function _payment(uint256 beneficiaryId, address payee, bytes32 nameHash, uint256 amount)
        internal
        view
        returns (MandateAccount.Payment memory p)
    {
        p = MandateAccount.Payment({
            invoiceId: keccak256(abi.encodePacked("invoice", beneficiaryId, amount)),
            beneficiaryId: beneficiaryId,
            payee: payee,
            payeeNameHash: nameHash,
            amount: amount,
            memoHash: keccak256("December retainer"),
            dueDate: block.timestamp + 7 days,
            validUntil: block.timestamp + 30 days,
            nonce: 1
        });
    }

    function _approve(MandateAccount.Payment memory p) internal view returns (bytes memory) {
        bytes32 digest =
            mandate.approvalDigest(p.invoiceId, p.beneficiaryId, p.payee, p.amount, p.validUntil, p.nonce);
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(ownerKey, digest);
        return abi.encodePacked(r, s, v);
    }

    function _expectRefused(MandateAccount.Payment memory p, bytes memory approval, uint8 code) internal {
        vm.prank(agent);
        vm.expectRevert(abi.encodeWithSelector(MandateAccount.Refused.selector, code));
        mandate.pay(p, approval);
    }

    /* ------------------------------ tests ------------------------------ */

    function test_SettlesVerifiedInvoice() public {
        MandateAccount.Payment memory p = _payment(merchantId, merchantWallet, MERCHANT_NAME, 1_200_000);

        vm.expectEmit(true, true, true, true, address(mandate));
        emit MandateAccount.PaymentSettled(
            p.invoiceId, merchantId, merchantWallet, 1_200_000, false, p.memoHash, p.dueDate
        );
        vm.prank(agent);
        mandate.pay(p, "");

        assertEq(token.balanceOf(merchantWallet), 1_200_000);
        assertEq(mandate.spentToday(), 1_200_000);
        assertTrue(mandate.invoiceUsed(p.invoiceId));
    }

    function test_PreviewMatchesOutcome() public {
        MandateAccount.Payment memory p = _payment(merchantId, merchantWallet, MERCHANT_NAME, 1_200_000);
        assertEq(mandate.preview(p, ""), mandate.OK());
    }

    function test_RejectsSpoofedInvoiceWithMerchantsName() public {
        // Attacker copies the verified name but swaps the payout address.
        MandateAccount.Payment memory p = _payment(merchantId, attacker, MERCHANT_NAME, 1_200_000);
        _expectRefused(p, "", mandate.REFUSED_ADDRESS_MISMATCH());
        assertEq(token.balanceOf(attacker), 0);
    }

    function test_RejectsNameMismatch() public {
        MandateAccount.Payment memory p =
            _payment(merchantId, merchantWallet, keccak256("Acme Studio Ltd"), 1_200_000);
        _expectRefused(p, "", mandate.REFUSED_NAME_MISMATCH());
    }

    function test_RejectsUnknownPayee() public {
        MandateAccount.Payment memory p = _payment(99, attacker, MERCHANT_NAME, 1_000_000);
        _expectRefused(p, "", mandate.REFUSED_UNKNOWN_PAYEE());
    }

    function test_RejectsInactivePayee() public {
        vm.prank(owner);
        mandate.setBeneficiaryActive(merchantId, false);
        MandateAccount.Payment memory p = _payment(merchantId, merchantWallet, MERCHANT_NAME, 1_000_000);
        _expectRefused(p, "", mandate.REFUSED_PAYEE_INACTIVE());
    }

    function test_RejectsDuplicateInvoice() public {
        MandateAccount.Payment memory p = _payment(merchantId, merchantWallet, MERCHANT_NAME, 1_000_000);
        vm.prank(agent);
        mandate.pay(p, "");
        _expectRefused(p, "", mandate.REFUSED_DUPLICATE_INVOICE());
    }

    function test_RejectsOverPerPaymentCap() public {
        MandateAccount.Payment memory p = _payment(merchantId, merchantWallet, MERCHANT_NAME, 2_000_001);
        _expectRefused(p, "", mandate.REFUSED_OVER_PER_PAYMENT_CAP());
    }

    function test_RejectsOverDailyCap() public {
        vm.prank(owner);
        mandate.setPolicy(4_000_000, DAILY, 4_000_000, 0);

        MandateAccount.Payment memory p1 = _payment(merchantId, merchantWallet, MERCHANT_NAME, 3_500_000);
        vm.prank(agent);
        mandate.pay(p1, "");
        assertEq(mandate.remainingToday(), DAILY - 3_500_000);

        MandateAccount.Payment memory p2 = _payment(accountingId, address(0xC0FFEE), ACCOUNTING_NAME, 3_500_000);
        _expectRefused(p2, "", mandate.REFUSED_OVER_DAILY_CAP());
    }

    function test_DailyCapResetsNextDay() public {
        MandateAccount.Payment memory p1 = _payment(merchantId, merchantWallet, MERCHANT_NAME, 1_900_000);
        vm.prank(agent);
        mandate.pay(p1, "");

        vm.warp(block.timestamp + 1 days + 1);
        MandateAccount.Payment memory p2 = _payment(accountingId, address(0xC0FFEE), ACCOUNTING_NAME, 1_900_000);
        vm.prank(agent);
        mandate.pay(p2, "");
        assertEq(token.balanceOf(address(0xC0FFEE)), 1_900_000);
    }

    function test_AboveThresholdRequiresApproval() public {
        MandateAccount.Payment memory p = _payment(merchantId, merchantWallet, MERCHANT_NAME, 2_000_001);
        // raise the cap so the only blocker is approval
        vm.prank(owner);
        mandate.setPolicy(3_000_000, DAILY, 2_000_000, 0);
        _expectRefused(p, "", mandate.REFUSED_APPROVAL_REQUIRED());
    }

    function test_OwnerApprovalSettlesAboveThreshold() public {
        vm.prank(owner);
        mandate.setPolicy(3_000_000, DAILY, 2_000_000, 0);
        MandateAccount.Payment memory p = _payment(merchantId, merchantWallet, MERCHANT_NAME, 2_400_000);
        bytes memory sig = _approve(p);

        vm.prank(agent);
        mandate.pay(p, sig);
        assertEq(token.balanceOf(merchantWallet), 2_400_000);
        assertTrue(mandate.approvalNonceUsed(p.nonce));
    }

    function test_ApprovalByNonOwnerIsRejected() public {
        vm.prank(owner);
        mandate.setPolicy(3_000_000, DAILY, 2_000_000, 0);
        MandateAccount.Payment memory p = _payment(merchantId, merchantWallet, MERCHANT_NAME, 2_400_000);

        (uint8 v, bytes32 r, bytes32 s) = vm.sign(0xBAD, mandate.approvalDigest(
            p.invoiceId, p.beneficiaryId, p.payee, p.amount, p.validUntil, p.nonce
        ));
        _expectRefused(p, abi.encodePacked(r, s, v), mandate.REFUSED_INVALID_APPROVAL());
    }

    function test_ApprovalCannotBeReplayedOnEditedAmount() public {
        vm.prank(owner);
        mandate.setPolicy(4_000_000, DAILY, 2_000_000, 0);
        MandateAccount.Payment memory p = _payment(merchantId, merchantWallet, MERCHANT_NAME, 2_100_000);
        bytes memory sig = _approve(p);
        p.amount = 3_900_000; // agent inflates the amount after the owner signed
        _expectRefused(p, sig, mandate.REFUSED_INVALID_APPROVAL());
    }

    function test_ExpiredInvoiceIsRejected() public {
        vm.warp(1_800_000_000);
        MandateAccount.Payment memory p = _payment(merchantId, merchantWallet, MERCHANT_NAME, 1_000_000);
        p.validUntil = block.timestamp - 1;
        _expectRefused(p, "", mandate.REFUSED_INVOICE_EXPIRED());
    }

    function test_PausedBlocksPayments() public {
        vm.prank(owner);
        mandate.setPaused(true);
        MandateAccount.Payment memory p = _payment(merchantId, merchantWallet, MERCHANT_NAME, 1_000_000);
        _expectRefused(p, "", mandate.REFUSED_PAUSED());
    }

    function test_PolicyExpiryBlocksPayments() public {
        vm.prank(owner);
        mandate.setPolicy(PER_TX, DAILY, THRESHOLD, block.timestamp + 1 hours);
        vm.warp(block.timestamp + 2 hours);
        MandateAccount.Payment memory p = _payment(merchantId, merchantWallet, MERCHANT_NAME, 1_000_000);
        _expectRefused(p, "", mandate.REFUSED_POLICY_EXPIRED());
    }

    function test_InsufficientBalanceIsRejected() public {
        vm.prank(owner);
        mandate.withdraw(owner, 9_900_000);
        MandateAccount.Payment memory p = _payment(merchantId, merchantWallet, MERCHANT_NAME, 1_000_000);
        _expectRefused(p, "", mandate.REFUSED_INSUFFICIENT_BALANCE());
    }

    function test_OnlyAgentCanPay() public {
        MandateAccount.Payment memory p = _payment(merchantId, merchantWallet, MERCHANT_NAME, 1_000_000);
        vm.prank(attacker);
        vm.expectRevert(MandateAccount.NotAgent.selector);
        mandate.pay(p, "");
    }

    function test_OnlyOwnerCanWithdraw() public {
        vm.prank(agent);
        vm.expectRevert(MandateAccount.NotOwner.selector);
        mandate.withdraw(agent, 1_000_000);
    }

    function test_OwnerCanWithdrawEverything() public {
        vm.prank(owner);
        mandate.withdraw(owner, 10_000_000);
        assertEq(token.balanceOf(owner), 10_000_000);
        assertEq(token.balanceOf(address(mandate)), 0);
    }

    function test_OnlyAgentCanRecordRefusal() public {
        vm.prank(attacker);
        vm.expectRevert(MandateAccount.NotAgent.selector);
        mandate.recordRefusal(keccak256("x"), 15, 1, bytes32(0));
    }

    function test_AgentRecordsRefusalOnChain() public {
        bytes32 invoiceId = keccak256("spoofed-1");
        vm.expectEmit(true, true, false, true, address(mandate));
        emit MandateAccount.RefusalRecorded(invoiceId, agent, 16, 1_200_000, MERCHANT_NAME);
        vm.prank(agent);
        mandate.recordRefusal(invoiceId, 16, 1_200_000, MERCHANT_NAME);
    }

    function test_OnlyOwnerCanChangePolicy() public {
        vm.prank(agent);
        vm.expectRevert(MandateAccount.NotOwner.selector);
        mandate.setPolicy(1, 1, 1, 0);
        vm.prank(agent);
        vm.expectRevert(MandateAccount.NotOwner.selector);
        mandate.setAgent(attacker);
    }

    function test_AgentRevocationStopsPayments() public {
        vm.prank(owner);
        mandate.setAgent(address(0));
        MandateAccount.Payment memory p = _payment(merchantId, merchantWallet, MERCHANT_NAME, 1_000_000);
        vm.prank(agent);
        vm.expectRevert(MandateAccount.NotAgent.selector);
        mandate.pay(p, "");
    }

    function test_ZeroAmountRejected() public {
        MandateAccount.Payment memory p = _payment(merchantId, merchantWallet, MERCHANT_NAME, 0);
        _expectRefused(p, "", mandate.REFUSED_ZERO_AMOUNT());
    }
}
