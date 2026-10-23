"""Deterministic target quotas; only distinct build variants count, never replays."""
from fractions import Fraction


def target_quotas(policy: dict, budget: int) -> list[dict]:
    if budget < 0:
        raise ValueError('budget must be nonnegative')
    os_weights = policy['os_weights']
    if sum(os_weights.values()) != 100 or any(v <= 0 for v in os_weights.values()):
        raise ValueError('OS weights must be positive and sum to 100')
    rows = []
    for os_name, weight in os_weights.items():
        arches = policy['arch_weights_within_os'][os_name]
        if sum(arches.values()) != 100 or any(v <= 0 for v in arches.values()):
            raise ValueError('architecture weights must be positive and sum to 100')
        for arch, arch_weight in arches.items():
            exact = Fraction(budget * weight * arch_weight, 10000)
            rows.append({'os': os_name, 'format': policy['format_by_os'][os_name], 'arch': arch,
                         'target_builds': int(exact), '_remainder': exact-int(exact)})
    remainder = budget - sum(r['target_builds'] for r in rows)
    ordered = sorted(rows, key=lambda r: (-r['_remainder'], r['os'], r['arch']))
    for row in ordered[:remainder]:
        row['target_builds'] += 1
    for row in rows:
        del row['_remainder']
    return rows
