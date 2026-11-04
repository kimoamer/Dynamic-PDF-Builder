"""
Extra comparison document for M7.4.

The M7 corpus has no long runs of continuous prose outside a technical manual,
so nothing in it would exercise columns. Organisation, people and figures here
are fictional, and the prose was written for this benchmark.
"""
from __future__ import annotations

from dynamic_pdf import DocumentBuilder

EDITORIAL_BRIEFING = """# Harbour Line Transit: Strategy Briefing 2026

## Executive Summary

Harbour Line carried 41 million passengers last year, its highest total since the network opened, and did so with fewer vehicles in service than in any of the previous four years. The improvement came from timetable changes rather than new capacity, which means the easy gains have now been taken and the next stage of growth will have to be paid for.

This briefing sets out the three choices the board must make before the budget round closes in March: how far to extend the eastern corridor, whether to replace the depot at Saltmarsh or refurbish it, and how quickly to move the bus fleet to battery power. Each choice is presented with the evidence available today and with the points on which that evidence is still weak.

## How the Network Changed

The timetable introduced in September moved four of the busiest routes to a fixed ten-minute interval across the whole working day. Before the change, those routes ran at intervals that varied between seven and sixteen minutes, and passengers on the outer sections regularly reported waits of more than twenty minutes when a vehicle was held at the central interchange.

Regular intervals made the service easier to explain and easier to run. Drivers now hand over at the same two points on every route, so a late arrival no longer travels down the line for the rest of the shift. Reliability, measured as the share of departures within two minutes of schedule, rose from 78 percent to 89 percent within one quarter.

The change also exposed a limit that the old timetable had hidden. On the eastern corridor the morning peak now fills vehicles before they reach Quayside, and the passengers left waiting are the ones who have the fewest alternatives. Standing loads above the agreed comfort level were recorded on 62 working days, compared with 19 the year before.

Staff survey results moved in the same direction as the service figures. Driver satisfaction with rosters rose for the first time in six years, and unplanned absence fell by a fifth. We should be careful about reading too much into a single year, but the supervisors who run the depots describe a calmer operation, and fewer late changes to duty sheets are visible in the rostering records.

## The Eastern Corridor

Three options have been costed for the corridor. The first adds peak-only short workings between Quayside and the central interchange, using vehicles released by the September timetable. It is cheap, can start within six months, and relieves the worst crowding, although it does nothing for the stops beyond Quayside.

The second option extends the fixed interval to Marlow Point and adds eleven vehicles. It serves the new housing at Tannery Fields, where the first 900 homes will be occupied next year, and it brings an estimated 6,000 additional passengers a day. The cost is mainly operating cost, and it depends on developer contributions that have been agreed in principle but not yet signed.

The third option is a segregated busway along the old rail alignment. It would cut journey times by nine minutes and would protect the service from road congestion for decades, but it needs a planning process of at least four years. We do not recommend committing to it now. We do recommend protecting the alignment so that the choice stays open.

Our recommendation is to start the short workings immediately and to approve the extension to Marlow Point once the developer agreement is signed. Those two steps can be reversed if demand falls short of the forecast, which matters because the forecast rests on a housing programme that has already slipped once.

| Option | Capital (£m) | Operating (£m a year) | Passengers a day | Earliest start |
|---|---:|---:|---:|---|
| Peak short workings | 0.4 | 1.1 | 2,300 | Q3 2026 |
| Extension to Marlow Point | 6.8 | 3.9 | 6,000 | Q2 2027 |
| Segregated busway | 58.0 | 2.6 | 9,500 | 2031 |

## Depot and Fleet

Saltmarsh depot was built for 120 vehicles and now houses 164. Vehicles are parked two deep overnight, which adds about forty minutes of shunting to every morning run-out and rules out the charging layout that a battery fleet would need. The building itself is sound, but the yard and the electrical supply are not.

A full replacement on the site would cost £31 million and would take the depot out of use in stages over three years. Refurbishment would cost £12 million and could be finished in fourteen months, but it would leave the capacity problem unsolved, and the network operator has warned that the grid connection cannot be upgraded twice at a reasonable price.

The fleet decision follows from the depot decision. Battery buses cost about 60 percent more to buy than the diesel vehicles they replace, and they save roughly a third of the running cost over a twelve-year life. The saving only appears if charging happens overnight at the depot, so a slower depot programme means a slower fleet programme, whatever the policy target says.

We recommend the full replacement, phased so that the first 40 charging bays are ready before the next diesel vehicles reach the end of their lives in 2028. That sequence avoids buying another generation of diesel vehicles, which would otherwise lock in their running costs until the end of the next decade.

## Risks and Next Steps

The largest risk is the funding gap in the second half of the plan. The current settlement runs to 2028 and the depot programme runs past it, so the board would be committing to spending that is not yet covered. We propose to bring a staged commitment, with a formal review before each phase, rather than a single approval for the whole programme.

The second risk is delivery capacity. Harbour Line has not managed a programme of this size since the network opened, and the project team has four people. The plan assumes that a programme director is appointed by June and that the procurement function is strengthened before the first main contract is let.

The third risk is public support for the disruption during construction. Residents near Saltmarsh have already raised concerns about night-time vehicle movements, and any change to the depot layout will need careful consultation. Officers will return in March with a consultation plan, a draft programme and a revised forecast for the eastern corridor.
"""


def editorial_briefing() -> DocumentBuilder:
    return DocumentBuilder.from_markdown(EDITORIAL_BRIEFING)
