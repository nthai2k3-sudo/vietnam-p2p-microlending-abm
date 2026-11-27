"""Agent definitions for Mesa 3.x micro-lending simulation."""
from mesa import Agent
import numpy as np


class Lender(Agent):
    """Supplies capital and reacts to pool yield and system-wide NPL."""

    def __init__(self, model, capital: float):
        super().__init__(model)
        self.capital = float(capital)
        self.deposited = 0.0
        self.withdrawn = 0.0

    def step(self):
        supply = self.model.supply_rate
        npl = self.model.npl_rate
        if supply > 0.06 and self.capital > 1.0:
            amount = min(self.capital, max(0.0, self.capital * 0.15))
            self.capital -= amount
            self.deposited += amount
            self.model.pool_cash += amount
        elif (supply < 0.05 or npl > 0.15) and self.deposited > 0:
            amount = min(self.deposited, self.model.pool_cash)
            self.deposited -= amount
            self.withdrawn += amount
            self.capital += amount
            self.model.pool_cash -= amount


class BorrowerBase(Agent):
    """Shared borrower state and repayment mechanics."""

    def __init__(self, model, income: float, living_cost: float, credit_score: int = 20):
        super().__init__(model)
        self.income = float(income)
        self.base_income = float(income)
        self.living_cost = float(living_cost)
        self.credit_score = int(credit_score)
        self.loan_principal = 0.0
        self.remaining_principal = 0.0
        self.monthly_due = 0.0
        self.months_left = 0
        self.collateral = 0.0
        self.guarantor_stake = 0.0
        self.is_defaulted = False
        self.total_borrowed = 0.0
        self.total_repaid = 0.0

    def available_surplus(self):
        income = self.income * (0.7 if 30 <= self.model.month <= 35 else 1.0)
        return max(0.0, income - self.living_cost)

    def _open_loan(self, amount: float, apr: float, collateral: float, stake: float = 0.0):
        self.loan_principal = amount
        self.remaining_principal = amount
        self.months_left = 6
        monthly_rate = apr / 12.0
        # Equal-principal schedule with interest on current outstanding balance.
        self.monthly_due = amount / self.months_left + amount * monthly_rate
        self.collateral = collateral
        self.guarantor_stake = stake
        self.total_borrowed += amount
        self.model.pool_cash -= amount
        self.model.locked_collateral += collateral + stake
        self.model.pool_borrowed += amount
        self.model.cumulative_disbursed += amount

    def _repay_month(self):
        if self.remaining_principal <= 0 or self.is_defaulted:
            return
        principal_payment = min(self.remaining_principal, self.loan_principal / 6.0)
        interest = self.remaining_principal * self.model.borrow_apr_for(self) / 12.0
        due = principal_payment + interest
        if self.available_surplus() < due:
            self._default()
            return
        self.remaining_principal -= principal_payment
        self.total_repaid += due
        self.model.pool_cash += principal_payment + interest * (1.0 - self.model.reserve_factor)
        self.model.pool_borrowed = max(0.0, self.model.pool_borrowed - principal_payment)
        self.model.reserve += interest * self.model.reserve_factor
        self.model.interest_paid += interest
        self.months_left -= 1
        if self.months_left <= 0 or self.remaining_principal < 1e-8:
            self.model.locked_collateral -= self.collateral + self.guarantor_stake
            self.collateral = 0.0
            self.guarantor_stake = 0.0
            self.credit_score = min(100, self.credit_score + 5)
            self.remaining_principal = 0.0
            self.model.completed_loans += 1

    def _default(self):
        if self.is_defaulted:
            return
        self.is_defaulted = True
        recovery = self.collateral + self.guarantor_stake
        self.model.locked_collateral -= recovery
        self.model.pool_cash += recovery
        self.model.pool_borrowed = max(0.0, self.model.pool_borrowed - self.remaining_principal)
        self.model.defaulted_principal += self.remaining_principal
        uncovered = max(0.0, self.remaining_principal - recovery)
        self.model.losses += uncovered
        reserve_coverage = min(self.model.reserve, uncovered)
        self.model.reserve -= reserve_coverage
        self.model.npl_events += 1
        self.credit_score = max(0, self.credit_score - 25)
        self.remaining_principal = 0.0
        self.collateral = 0.0
        self.guarantor_stake = 0.0


class HonestBorrower(BorrowerBase):
    """Borrows for essential working-capital/consumption needs."""

    def step(self):
        if self.model.month == 1:
            self._try_borrow()
        elif self.remaining_principal > 0:
            self._repay_month()
        elif not self.is_defaulted and self.model.month % 8 == 0:
            self._try_borrow()

    def _try_borrow(self):
        if self.is_defaulted:
            return
        desired = min(4.0, max(1.0, self.available_surplus() * 2.0))
        self.model.originate_loan(self, desired)


class StrategicDefaulter(BorrowerBase):
    """Behavioral proxy: builds reputation, then strategically defaults."""

    def __init__(self, model, income, living_cost, credit_score=20):
        super().__init__(model, income, living_cost, credit_score)
        self.successful_payments = 0
        self.strategy_triggered = False

    def step(self):
        if self.remaining_principal > 0 and not self.is_defaulted:
            # Strategic borrower pays the first two installments to build score.
            if self.successful_payments >= 2 and self.remaining_principal > self.collateral + self.guarantor_stake:
                self._default()
            else:
                before = self.remaining_principal
                self._repay_month()
                if self.remaining_principal < before:
                    self.successful_payments += 1
        elif not self.is_defaulted and self.model.month in (1, 10, 20):
            self.model.originate_loan(self, 5.0)
