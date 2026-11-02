from portal import actions, ui

account = ui.account()
ui.header("Decide", "To verify", "Work the field teams recorded as completed. Verify it, or reopen it with a reason.")
ui.action_cards(actions.list_actions(ui.connection(), account["UserId"], "verify"), "verify",
                empty="No completed work is waiting for verification.")
