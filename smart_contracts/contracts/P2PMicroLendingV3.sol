// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import "@openzeppelin/contracts/utils/ReentrancyGuard.sol";
import "@openzeppelin/contracts/access/Ownable.sol";

/// @notice Educational V3 prototype. Not audited and not for real funds.
contract P2PMicroLendingV3 is ReentrancyGuard, Ownable {
    using SafeERC20 for IERC20;

    uint256 public constant WAD = 1e18;
    uint256 public constant BPS = 10_000;
    uint256 public constant MONTH = 30 days;
    uint256 public constant RESERVE_FACTOR_BPS = 1_000; // 10%
    uint256 public constant GUARANTOR_SHARE_BPS = 2_500; // 25%
    uint256 public constant MAX_GUARANTEE_BPS = 3_000; // 30%
    uint256 public constant MIN_BORROW_RATE = 1e16; // 1% APR

    IERC20 public immutable token;
    uint256 public poolCash;
    uint256 public totalBorrowed;
    uint256 public protocolReserve;

    uint256 public baseRate = 10e16;       // 10% APR, WAD
    uint256 public slope1 = 12e16;         // 12% APR
    uint256 public slope2 = 80e16;         // 80% APR
    uint256 public optimalUtilization = 80e16;
    uint256 public gamma = 5e14;           // 0.05 percentage point per score
    uint256 public constant CR_MAX = 5e17; // 50%

    struct UserProfile {
        uint256 creditScore;
        uint256 activeLoanAmount;
        uint256 collateralLocked;
        uint256 dueTimestamp;
        address guarantorAddress;
    }

    struct Loan {
        uint256 principal;
        uint256 outstanding;
        uint256 accruedInterest;
        uint256 lastAccrual;
        uint256 dueTimestamp;
        uint256 borrowerCollateral;
        uint256 guarantorStake;
        address guarantor;
        bool active;
    }

    mapping(address => UserProfile) public profiles;
    mapping(address => Loan) public loans;
    mapping(address => uint256) public lenderDeposits;
    mapping(address => uint256) public guaranteeAllowance;
    mapping(address => mapping(address => uint256)) public guaranteeConsent;

    event Deposited(address indexed lender, uint256 amount);
    event Withdrawn(address indexed lender, uint256 amount);
    event GuaranteeApproved(address indexed guarantor, address indexed borrower, uint256 amount);
    event Borrowed(address indexed borrower, uint256 amount, uint256 collateral, address indexed guarantor, uint256 stake, uint256 apr);
    event Repaid(address indexed borrower, uint256 principal, uint256 interest, uint256 guarantorReward, uint256 reserveAmount);
    event DefaultLiquidated(address indexed borrower, address indexed guarantor, uint256 recovered, uint256 badDebt);
    event CreditScoreUpdated(address indexed user, uint256 newScore);

    constructor(address tokenAddress) Ownable(msg.sender) {
        require(tokenAddress != address(0), "zero token");
        token = IERC20(tokenAddress);
    }

    function _profile(address user) internal returns (UserProfile storage p) {
        p = profiles[user];
        if (p.creditScore == 0) p.creditScore = 20;
    }

    function getUtilizationRate() public view returns (uint256) {
        uint256 denominator = poolCash + totalBorrowed;
        if (denominator == 0) return 0;
        return (totalBorrowed * WAD) / denominator;
    }

    function getBorrowRate(address user) public view returns (uint256) {
        uint256 score = profiles[user].creditScore;
        if (score == 0) score = 20;
        uint256 u = getUtilizationRate();
        uint256 rate;
        if (u <= optimalUtilization) {
            rate = baseRate + (u * slope1) / optimalUtilization;
        } else {
            rate = baseRate + slope1 + ((u - optimalUtilization) * slope2) / (WAD - optimalUtilization);
        }
        uint256 discount = gamma * score;
        rate = rate > discount ? rate - discount : 0;
        if (rate < MIN_BORROW_RATE) rate = MIN_BORROW_RATE;
        return rate;
    }

    function getCollateralRatio(address user) public view returns (uint256) {
        uint256 score = profiles[user].creditScore;
        if (score == 0) score = 20;
        if (score > 100) score = 100;
        return (CR_MAX * (100 - score)) / 100;
    }

    function getSupplyRate() external view returns (uint256) {
        uint256 utilization = getUtilizationRate();
        uint256 representativeBorrowRate = getBorrowRate(address(0));
        return (representativeBorrowRate * utilization * (BPS - RESERVE_FACTOR_BPS)) / (WAD * BPS);
    }

    function deposit(uint256 amount) external nonReentrant {
        require(amount > 0, "zero amount");
        token.safeTransferFrom(msg.sender, address(this), amount);
        lenderDeposits[msg.sender] += amount;
        poolCash += amount;
        emit Deposited(msg.sender, amount);
    }

    function withdraw(uint256 amount) external nonReentrant {
        require(amount > 0 && lenderDeposits[msg.sender] >= amount, "invalid amount");
        require(poolCash >= amount, "insufficient liquidity");
        lenderDeposits[msg.sender] -= amount;
        poolCash -= amount;
        token.safeTransfer(msg.sender, amount);
        emit Withdrawn(msg.sender, amount);
    }

    /// @notice Guarantor pre-commits a maximum stake for a specific borrower.
    function approveGuarantee(address borrower, uint256 amount) external {
        require(borrower != address(0) && borrower != msg.sender, "invalid borrower");
        require(amount > 0, "zero amount");
        guaranteeConsent[msg.sender][borrower] = amount;
        emit GuaranteeApproved(msg.sender, borrower, amount);
    }

    function borrow(uint256 amount, address guarantor) external nonReentrant {
        require(amount > 0 && amount <= poolCash, "invalid amount");
        UserProfile storage p = _profile(msg.sender);
        require(p.activeLoanAmount == 0 && !loans[msg.sender].active, "active loan");
        uint256 apr = getBorrowRate(msg.sender);
        uint256 requiredCollateral = (amount * getCollateralRatio(msg.sender)) / WAD;
        uint256 borrowerCollateral;
        uint256 stake;

        if (guarantor != address(0)) {
            require(p.creditScore < 40, "guarantee only for low score");
            require(guarantor != msg.sender, "self guarantee");
            UserProfile storage gp = _profile(guarantor);
            require(gp.creditScore >= 70, "guarantor score too low");
            stake = (amount * MAX_GUARANTEE_BPS) / BPS;
            require(guaranteeConsent[guarantor][msg.sender] >= stake, "guarantee not approved");
            guaranteeConsent[guarantor][msg.sender] -= stake;
            token.safeTransferFrom(guarantor, address(this), stake);
            // Social stake substitutes for part of required collateral.
            borrowerCollateral = requiredCollateral > stake ? requiredCollateral - stake : 0;
        } else {
            borrowerCollateral = requiredCollateral;
        }

        if (borrowerCollateral > 0) {
            token.safeTransferFrom(msg.sender, address(this), borrowerCollateral);
        }

        poolCash -= amount;
        totalBorrowed += amount;
        p.activeLoanAmount = amount;
        p.collateralLocked = borrowerCollateral;
        p.guarantorAddress = guarantor;
        p.dueTimestamp = block.timestamp + 6 * MONTH;

        loans[msg.sender] = Loan({
            principal: amount,
            outstanding: amount,
            accruedInterest: 0,
            lastAccrual: block.timestamp,
            dueTimestamp: p.dueTimestamp,
            borrowerCollateral: borrowerCollateral,
            guarantorStake: stake,
            guarantor: guarantor,
            active: true
        });

        token.safeTransfer(msg.sender, amount);
        emit Borrowed(msg.sender, amount, borrowerCollateral, guarantor, stake, apr);
    }

    function _accrue(Loan storage loan, address borrower) internal {
        if (!loan.active) return;
        uint256 elapsed = block.timestamp - loan.lastAccrual;
        if (elapsed == 0) return;
        uint256 apr = getBorrowRate(borrower);
        uint256 interest = (loan.outstanding * apr * elapsed) / (WAD * 365 days);
        loan.accruedInterest += interest;
        loan.lastAccrual = block.timestamp;
    }

    function repay() external nonReentrant {
        Loan storage loan = loans[msg.sender];
        require(loan.active, "no active loan");
        _accrue(loan, msg.sender);
        uint256 principal = loan.outstanding;
        uint256 interest = loan.accruedInterest;
        uint256 totalDue = principal + interest;
        require(totalDue > 0, "nothing due");
        token.safeTransferFrom(msg.sender, address(this), totalDue);

        uint256 guarantorReward = (interest * GUARANTOR_SHARE_BPS) / BPS;
        uint256 reserveAmount = (interest * RESERVE_FACTOR_BPS) / BPS;
        uint256 lenderInterest = interest - guarantorReward - reserveAmount;

        poolCash += principal + lenderInterest;
        totalBorrowed -= principal;
        protocolReserve += reserveAmount;

        if (loan.borrowerCollateral > 0) token.safeTransfer(msg.sender, loan.borrowerCollateral);
        if (loan.guarantorStake > 0) {
            token.safeTransfer(loan.guarantor, loan.guarantorStake);
            if (guarantorReward > 0) token.safeTransfer(loan.guarantor, guarantorReward);
        } else if (guarantorReward > 0) {
            // No guarantor means the lender pool retains this share.
            poolCash += guarantorReward;
        }

        UserProfile storage p = _profile(msg.sender);
        p.creditScore = p.creditScore + 5 > 100 ? 100 : p.creditScore + 5;
        p.activeLoanAmount = 0;
        p.collateralLocked = 0;
        p.dueTimestamp = 0;
        p.guarantorAddress = address(0);

        emit Repaid(msg.sender, principal, interest, guarantorReward, reserveAmount);
        delete loans[msg.sender];
    }

    function liquidateDefault(address borrower) external nonReentrant {
        Loan storage loan = loans[borrower];
        require(loan.active, "no active loan");
        require(block.timestamp > loan.dueTimestamp, "not overdue");
        _accrue(loan, borrower);

        uint256 recovery = loan.borrowerCollateral + loan.guarantorStake;
        uint256 debt = loan.outstanding + loan.accruedInterest;
        uint256 principal = loan.outstanding;
        uint256 badDebt = debt > recovery ? debt - recovery : 0;

        totalBorrowed -= principal;
        poolCash += recovery;
        if (protocolReserve >= badDebt) {
            protocolReserve -= badDebt;
            poolCash += badDebt;
            badDebt = 0;
        }

        UserProfile storage bp = _profile(borrower);
        bp.creditScore = bp.creditScore > 25 ? bp.creditScore - 25 : 0;
        bp.activeLoanAmount = 0;
        bp.collateralLocked = 0;
        bp.dueTimestamp = 0;
        bp.guarantorAddress = address(0);

        if (loan.guarantor != address(0)) {
            UserProfile storage gp = _profile(loan.guarantor);
            gp.creditScore = gp.creditScore > 15 ? gp.creditScore - 15 : 0;
            emit CreditScoreUpdated(loan.guarantor, gp.creditScore);
        }

        emit DefaultLiquidated(borrower, loan.guarantor, recovery, badDebt);
        emit CreditScoreUpdated(borrower, bp.creditScore);
        delete loans[borrower];
    }

    function setRateParameters(uint256 base, uint256 s1, uint256 s2, uint256 optimal) external onlyOwner {
        require(optimal > 0 && optimal < WAD, "bad optimal utilization");
        require(base <= 2e18 && s1 <= 2e18 && s2 <= 5e18, "rate too high");
        baseRate = base;
        slope1 = s1;
        slope2 = s2;
        optimalUtilization = optimal;
    }

    function fundReserve(uint256 amount) external onlyOwner {
        require(amount > 0, "zero amount");
        token.safeTransferFrom(msg.sender, address(this), amount);
        protocolReserve += amount;
    }
}
