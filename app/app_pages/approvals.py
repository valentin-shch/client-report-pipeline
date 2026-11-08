import streamlit as st

from control import (approval_passcode, approve_and_send, error_type, load_reports, report_html,
                     retry, stop_if_unavailable, try_passcode)
from lib import report_frame

st.title("Approvals")
st.caption("Reports waiting for a person to send them, and what happened to the ones already sent.")

if "unlocked" not in st.session_state:
    st.session_state.unlocked = False

passcode = approval_passcode()
if passcode is None:
    st.info("Sending is turned off here: no approval passcode is set.", icon=":material/lock:")
elif not st.session_state.unlocked:
    with st.container(border=True):
        st.markdown("Approving is restricted in the demo. Everything below is visible; sending "
                    "needs the passcode.")
        entered = st.text_input("Passcode", type="password", key="passcode")
        if st.button("Unlock", key="unlock", icon=":material/lock_open:"):
            outcome = stop_if_unavailable(try_passcode, entered, passcode)
            if outcome == "ok":
                st.session_state.unlocked = True
                st.rerun()
            elif outcome == "locked":
                st.error("Too many wrong tries. Approvals are locked for an hour.", icon=":material/lock:")
            else:
                st.error("Wrong passcode.")

# What happened after the last click, carried over the rerun that refreshes the list.
if note := st.session_state.pop("outcome_note", None):
    kind, message = note
    getattr(st, kind)(message)

reports = stop_if_unavailable(load_reports)
can_send = passcode is not None and st.session_state.unlocked

MESSAGES = {
    "sent": ("success", "Sent."),
    "changed": ("warning", "This report has changed since you opened the page. Look at it again first."),
    "cap_reached": ("warning", "Today's sending limit is reached. Try again tomorrow."),
    "no_recipients": ("error", "This client has no recipients configured."),
    "not_approved": ("warning", "Someone else already handled this report."),
    "not_found": ("warning", "This report no longer exists."),
    "failed": ("error", "The email couldn't be sent. It's listed below with a Retry button."),
    "no_mailer": ("error", "Email isn't set up here, so nothing was approved."),
}


def act(action, *args) -> None:
    outcome = stop_if_unavailable(action, *args)
    st.session_state.outcome_note = MESSAGES.get(outcome, ("info", outcome))
    st.rerun()


def heading(report) -> None:
    st.markdown(f"**{report['subject']}**")  # the subject already names the client and week
    alerts = int(report["alerts"])
    st.caption(f"{alerts} alert{'' if alerts == 1 else 's'} flagged")


st.subheader("Waiting for approval")
pending = reports[reports["status"] == "pending"]
if pending.empty:
    st.markdown("Nothing waiting. The next run's reports land here.")
for _, report in pending.iterrows():
    with st.container(border=True):
        heading(report)
        # Previews are loaded only when asked for: each is a whole HTML email.
        if st.toggle("Preview", key=f"preview-{report['id']}"):
            report_frame(stop_if_unavailable(report_html, int(report["id"])))
        if st.button("Approve and send", key=f"send-{report['id']}", type="primary",
                     icon=":material/send:", disabled=not can_send):
            act(approve_and_send, int(report["id"]), int(report["run_id"]))

st.subheader("Recent")
done = reports[reports["status"] != "pending"]
if done.empty:
    st.markdown("Nothing sent yet.")
for _, report in done.iterrows():
    with st.container(border=True):
        heading(report)
        if report["status"] == "sent":
            st.markdown(f":green[:material/check_circle:] Sent {report['sent_at']:%d %b %Y, %H:%M} UTC")
        elif report["status"] == "send_failed":
            st.markdown(f":red[:material/error:] Failed to send ({error_type(report['error'])})")
            if st.button("Retry", key=f"retry-{report['id']}", icon=":material/refresh:", disabled=not can_send):
                act(retry, int(report["id"]))
        elif report["status"] == "sending":
            st.markdown(":orange[:material/hourglass_top:] Stuck mid-send. Nobody knows whether the "
                        "email went: check the inbox before doing anything.")
        else:
            st.markdown(":gray[:material/schedule:] Approved, not sent yet")
