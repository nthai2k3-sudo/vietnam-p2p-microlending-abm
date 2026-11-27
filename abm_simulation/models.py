"""Three comparable Mesa 3.x models: V1, V2 and V3."""
from mesa import Model, DataCollector
import numpy as np
from .agents import Lender, HonestBorrower, StrategicDefaulter


class MicroLendingBase(Model):
    def __init__(self, seed=42, version="V1", n_lenders=100, n_honest=325, n_strategic=75):
        super().__init__(seed=seed)
        self.version = version
        self.month = 0
        self.pool_cash = 0.0
        self.pool_borrowed = 0.0
        self.locked_collateral = 0.0
        self.reserve = 0.0
        self.reserve_factor = 0.10
        self.cumulative_disbursed = 0.0
        self.defaulted_principal = 0.0
        self.losses = 0.0
        self.interest_paid = 0.0
        self.npl_events = 0
        self.completed_loans = 0
        self.borrow_apr_avg = 0.18 if version == "V1" else 0.10
        self.supply_rate = 0.0
        self._last_utilization = 0.0
        self._agent_counter = 0

        # Same seeded random stream and population construction in all versions.
        for _ in range(n_lenders):
            lender = Lender(self, self.rng.uniform(50, 200))
            # Bootstrap liquidity: each lender initially supplies 20% of capital.
            # Without seed liquidity, utilization and supply APR are both zero,
            # so a purely rate-triggered deposit rule would create a deadlock.
            seed_deposit = lender.capital * 0.20
            lender.capital -= seed_deposit
            lender.deposited += seed_deposit
            self.pool_cash += seed_deposit
        for _ in range(n_honest):
            income = max(5.0, self.rng.normal(12, 3))
            living = max(4.0, self.rng.normal(7.0, 1.0))
            self.add_agent(HonestBorrower(self, income, living))
        for _ in range(n_strategic):
            income = max(5.0, self.rng.normal(12, 3))
            living = max(4.0, self.rng.normal(7.0, 1.0))
            self.add_agent(StrategicDefaulter(self, income, living))

        self.datacollector = DataCollector(model_reporters={
            "month": lambda m: m.month,
            "cash": lambda m: m.pool_cash,
            "borrowed": lambda m: m.pool_borrowed,
            "reserve": lambda m: m.reserve,
            "TVL": lambda m: m.pool_cash + m.pool_borrowed + m.locked_collateral,
            "utilization": lambda m: m.utilization,
            "borrow_apr": lambda m: m.borrow_apr_avg,
            "supply_apr": lambda m: m.supply_rate,
            "NPL": lambda m: m.npl_rate,
            "cumulative_disbursed": lambda m: m.cumulative_disbursed,
            "defaulted_principal": lambda m: m.defaulted_principal,
            "losses": lambda m: m.losses,
            "interest_paid": lambda m: m.interest_paid,
        })

    def add_agent(self, agent):
        # Mesa 3.x registers agents through Agent.__init__; helper retained for clarity.
        return agent

    @property
    def utilization(self):
        total = self.pool_cash + self.pool_borrowed
        return self.pool_borrowed / total if total > 1e-12 else 0.0

    @property
    def npl_rate(self):
        return self.defaulted_principal / self.cumulative_disbursed if self.cumulative_disbursed > 1e-12 else 0.0

    def score(self, borrower):
        return borrower.credit_score if self.version != "V1" else 20

    def borrow_apr_for(self, borrower):
        if self.version == "V1":
            return 0.18
        return self._kink_rate(self.utilization, self.score(borrower))

    def _kink_rate(self, utilization, score):
        base, opt, slope1, slope2, gamma = 0.10, 0.80, 0.12, 0.80, 0.0005
        if utilization <= opt:
            rate = base + (utilization / opt) * slope1 - gamma * score
        else:
            rate = base + slope1 + ((utilization - opt) / (1 - opt)) * slope2 - gamma * score
        return float(np.clip(rate, 0.01, 1.50))

    def _collateral_ratio(self, borrower):
        if self.version == "V1":
            return 0.0
        return 0.50 * (1.0 - self.score(borrower) / 100.0)

    def originate_loan(self, borrower, requested):
        if borrower.is_defaulted or borrower.remaining_principal > 0:
            return False
        score = self.score(borrower)
        limit = 10.0 if self.version == "V1" else 5.0 + 0.25 * score
        amount = min(float(requested), limit, self.pool_cash)
        if amount < 0.5:
            return False
        collateral_required = amount * self._collateral_ratio(borrower)
        stake = 0.0
        collateral = collateral_required
        if self.version == "V3" and score < 40:
            # V3 social collateral: a pooled social guarantor stake may replace
            # the missing borrower collateral, up to 30% of principal.
            stake = min(amount * 0.30, collateral_required)
            collateral = collateral_required - stake
        # Borrower must have enough cash to post direct collateral in this stylized model.
        if collateral > max(0.0, borrower.available_surplus() * 2.0):
            return False
        if self.version != "V3" and collateral > max(0.0, borrower.available_surplus() * 2.0):
            return False
        apr = self.borrow_apr_for(borrower)
        borrower._open_loan(amount, apr, collateral, stake)
        return True

    def step(self):
        self.month += 1
        # Update pool rates before agents make monthly decisions.
        self._last_utilization = self.utilization
        if self.version == "V1":
            self.borrow_apr_avg = 0.18
        else:
            scores = [a.credit_score for a in self.agents if isinstance(a, (HonestBorrower, StrategicDefaulter))]
            avg_score = float(np.mean(scores)) if scores else 20.0
            self.borrow_apr_avg = self._kink_rate(self.utilization, avg_score)
        self.supply_rate = self.borrow_apr_avg * self.utilization * (1 - self.reserve_factor)
        self.agents.shuffle_do("step")
        self.datacollector.collect(self)

    def run(self, steps=60):
        for _ in range(steps):
            self.step()
        return self.datacollector.get_model_vars_dataframe()


class MicroLendingV1(MicroLendingBase):
    def __init__(self, seed=42):
        super().__init__(seed=seed, version="V1")


class MicroLendingV2(MicroLendingBase):
    def __init__(self, seed=42):
        super().__init__(seed=seed, version="V2")


class MicroLendingV3(MicroLendingBase):
    def __init__(self, seed=42):
        super().__init__(seed=seed, version="V3")
