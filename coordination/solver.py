"""Deterministic maximum bipartite matching for enumerated 30-minute cells.
NOT a medical optimizer; no claim of optimality outside this finite candidate graph.
Oldest-first processing retains an earlier matched request when later ones reroute it.
"""
from dataclasses import dataclass

@dataclass(frozen=True)
class MatchResult:
    pairs: tuple
    unassigned: tuple
    algorithm: str='augmenting_path_maximum_matching'
    status: str='OPTIMAL_FOR_ENUMERATED_GRAPH'

def maximum_matching(request_ids, candidates):
    ids=tuple(request_ids)
    if len(ids)>60 or len(set(ids))!=len(ids):raise ValueError('At most 60 distinct requests')
    choices={i:tuple(dict.fromkeys(candidates.get(i,()))) for i in ids}
    if sum(map(len,choices.values()))>12000:raise ValueError('Candidate graph too large')
    owner={}
    def place(i,seen):
        for cell in choices[i]:
            if cell in seen:continue
            seen.add(cell)
            if cell not in owner or place(owner[cell],seen):
                owner[cell]=i;return True
        return False
    for i in ids:place(i,set())
    by_request={i:cell for cell,i in owner.items()}
    return MatchResult(tuple((i,by_request[i]) for i in ids if i in by_request),
        tuple(i for i in ids if i not in by_request))

def overlaps(a,b,c,d):return a<d and c<b
