# Patient booking and clinic information

Baseline `0f6755b`. The first release covers the patient home, service detail, slot selection, confirmation and result on web and WeChat.

- **PB-01** A patient reviewing a new appointment, report follow-up or reschedule sees the proposed arrangement and the confirmation action. Going back keeps the relevant search filters. Reviewing an arrangement saves no visit.
- **PB-02** During confirmation, a patient sees progress and cannot confirm twice. A saved result opens its exact visit. A rejected confirmation explains how to reselect or return to the source visit. A rejected reschedule retains the original visit.
- **PB-03** After sending a confirmation whose outcome cannot be established, a patient can read the receipt for that exact attempt. A missing receipt is still unconfirmed. Reading a receipt never creates or changes a visit. The same account, workspace, selected patient and current appointment authorization must still apply.
- **PB-04** A patient can identify the intended audience, location, duration, scope, preparation, fee terms and next action from the same published clinic description on both clients. Published service data supplies all factual terms. Use the existing manager preview and publish process for clinic content.
- **PB-05** The home foregrounds the current task for the visitor or selected patient. Each page has one primary action for the current state. Secondary actions remain reachable, including under text enlargement and on a narrow device.
- **PB-06** An invited teacher can select an assigned synthetic role and see the existing username and password fields filled. Login still requires the normal submit action. WeChat offers patient, appointment delegate and medical proxy profiles. Employee workbench roles use the web login. Manual login remains available with and without a valid invitation.

Validate on independent synthetic data. Trial promotion requires the same integrated candidate to pass the web, WeChat tool and real-phone flow with debug disabled.
