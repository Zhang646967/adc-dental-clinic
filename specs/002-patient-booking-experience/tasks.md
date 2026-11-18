# Acceptance

| ID | Check |
| --- | --- |
| PB-01 | Open a confirmation without submitting. Both clients hide result recovery, show the booking facts and preserve filters when returning. Visit and receipt counts stay fixed. |
| PB-02 | Confirm once, open the exact visit, and read it across clients. Duplicate confirmation produces one visit and receipt. A newly occupied target leaves an existing appointment intact. |
| PB-03 | Test a request that never reaches the server and a committed response that is lost. Only the latter returns a visit from the receipt query. The lookup creates zero visits or receipts. A different patient/account and a stale authorization cannot read it. |
| PB-04 | Check the same service type at two stores. Compare actual name, duration, fee basis, preparation and action between clients. Check owner, visitor and delegated home behavior. |
| PB-05 | Verify page hierarchy, wrapping, large text, keyboard focus and return controls on web. Verify mobile size and safe areas in the WeChat tool and the normal, debug-disabled scan, directory, login, booking and readback on a phone. |
| PB-06 | Open an invited login, select two different roles and check that only the form fields change before submit. Check actual patient and staff login, separate channels, invalid and expired invitations, and typing credentials manually. Test the parameterized preview with domain checks enabled. |

The frozen handoff records build identity and the independent fixture accounts and case steps. The release receipt records the executed versions and result of each check.
