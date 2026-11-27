const { ethers } = require("hardhat");

async function main() {
  const [owner, lender, borrower, guarantor, defaultBorrower] = await ethers.getSigners();
  const unit = ethers.parseUnits;

  const Token = await ethers.getContractFactory("MockVNDT");
  const token = await Token.deploy();
  await token.waitForDeployment();

  const Protocol = await ethers.getContractFactory("P2PMicroLendingV3");
  const protocol = await Protocol.deploy(await token.getAddress());
  await protocol.waitForDeployment();

  const million = unit("1000000", 18);
  const lenderFunds = million * 100n;
  for (const account of [lender, borrower, guarantor, defaultBorrower]) {
    await (await token.mint(account.address, lenderFunds)).wait();
  }

  await (await token.connect(lender).approve(await protocol.getAddress(), lenderFunds)).wait();
  await (await protocol.connect(lender).deposit(lenderFunds)).wait();

  // Build guarantor reputation through ten small, fully repaid loans.
  // Each successful repayment adds five points: 20 -> 70.
  const reputationLoan = unit("1000", 18);
  const reputationCollateral = reputationLoan * 40n / 100n;
  await (await token.connect(guarantor).approve(await protocol.getAddress(), lenderFunds)).wait();
  for (let i = 0; i < 10; i++) {
    await (await protocol.connect(guarantor).borrow(reputationLoan, ethers.ZeroAddress)).wait();
    await (await token.connect(guarantor).approve(await protocol.getAddress(), unit("2000", 18))).wait();
    await (await protocol.connect(guarantor).repay()).wait();
  }
  const guarantorProfile = await protocol.profiles(guarantor.address);
  console.log("Guarantor credit score:", guarantorProfile.creditScore.toString());

  // Flow A: guarantee approval -> social-stake loan -> repayment.
  const loanAmount = million * 2n;
  const stake = loanAmount * 30n / 100n;
  await (await token.connect(guarantor).approve(await protocol.getAddress(), lenderFunds)).wait();
  await (await protocol.connect(guarantor).approveGuarantee(borrower.address, stake)).wait();
  // At score 20, required collateral is 40%; 30% is replaced by guarantor stake.
  const residualCollateral = loanAmount * 10n / 100n;
  await (await token.connect(borrower).approve(await protocol.getAddress(), residualCollateral)).wait();
  await (await protocol.connect(borrower).borrow(loanAmount, guarantor.address)).wait();
  await (await token.connect(borrower).approve(await protocol.getAddress(), million * 10n)).wait();
  await (await protocol.connect(borrower).repay()).wait();
  console.log("Guarantee + borrow + repay flow completed.");

  // Flow B: separate borrower defaults after the six-month maturity.
  const collateralB = loanAmount * 40n / 100n;
  await (await token.connect(defaultBorrower).approve(await protocol.getAddress(), collateralB)).wait();
  await (await protocol.connect(defaultBorrower).borrow(loanAmount, ethers.ZeroAddress)).wait();
  await ethers.provider.send("evm_increaseTime", [181 * 24 * 60 * 60]);
  await ethers.provider.send("evm_mine", []);
  await (await protocol.connect(owner).liquidateDefault(defaultBorrower.address)).wait();
  console.log("Default liquidation flow completed.");

  console.log("Pool cash:", ethers.formatUnits(await protocol.poolCash(), 18));
  console.log("Protocol reserve:", ethers.formatUnits(await protocol.protocolReserve(), 18));
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
