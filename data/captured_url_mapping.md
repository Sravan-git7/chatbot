# Captured pagecontent URLs -> guides

* evidence mode: **response_loio (saved responses: captured_responses)** (`response_loio` = authoritative replay; `card_page_id` = local card match only, loio check pending)

| # | numeric id | build | page id | card match (topic→guide) | response loio | → guide | decision |
|--:|---|---|---|---|---|---|---|
| 1 | 40374657 | 1779 | `8990d053` | #5→021b182b | 2ac7fe29 | - | **CARD_MISMATCH** |
| 2 | 40374682 | 1779 | `8082ce53` | #2→f4a255a5 | f4a255a5 | f4a255a5 | **MAPPED** |
| 3 | 40374657 | 1779 | `4d76765c` | #7→2ac7fe29 | 2ac7fe29 | 2ac7fe29 | **MAPPED** |
| 4 | 40404052 | 78 | `147bce53` | #11→ed84b70c | ed84b70c | ed84b70c | **MAPPED** |
| 5 | 40374633 | 1779 | `cc7bce53` | #14→a003b275 | a003b275 | a003b275 | **MAPPED** |
| 6 | 40374790 | 1779 | `790dc553` | #24→94424864 | 94424864 | 94424864 | **MAPPED** |
| 7 | 40374490 | 1779 | `b1a202c9` | #18→94424864 | e4375c1c | - | **NOT_A_CARD_GUIDE** |

## Why

1. CARD_MISMATCH: response loio 2ac7fe29 but the card(s) carrying this page id [5] name guide(s) ['021b182b']; identity not confirmed, nothing registered for this URL
2. MAPPED: response deliverable.loio == f4a255a5de524e3992155767996fb1fd, currentPage == requested page, card(s) [2] agree
3. MAPPED: response deliverable.loio == 2ac7fe29a0c94cdd88fb80c2cb9f7758, currentPage == requested page, card(s) [7] agree
4. MAPPED: response deliverable.loio == ed84b70c199d4470ae2e5ccb93b2e45b, currentPage == requested page, card(s) [11] agree
5. MAPPED: response deliverable.loio == a003b275c98148ee8a4c3fafe9588fe3, currentPage == requested page, card(s) [14] agree
6. MAPPED: response deliverable.loio == 9442486404b54071b4ebeab6a16628e7, currentPage == requested page, card(s) [24] agree
7. NOT_A_CARD_GUIDE: response loio e4375c1cad104b2eb7d027369bd76638 is not referenced by any of the 29 cards; not registered
