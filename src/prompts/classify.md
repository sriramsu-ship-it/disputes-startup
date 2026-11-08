<!-- template_id: classify | schema: disputes.agents.schemas.CLASSIFY | requirement: R-06 -->
## system
{{RULES}}

Task: classify the consumer's dispute into a SET of categories from this closed list:
- PAYMENT_HISTORY: lateness, days past due, on-time payment, payment ratings for particular months, payment arrangements (deferral, forbearance, hardship plans) affecting how months were reported.
- BALANCE: the amount owed, current balance or a specific dollar figure being wrong.
- ACCOUNT_STATUS: whether the account is open, closed, paid in full, charged off, or similar status.
- IDENTITY_FRAUD: the consumer says the account, or activity on it, is not theirs (identity theft, never opened it, does not recognise the lender, someone used their details). Indirect wording counts.
- OTHER: personal details such as name, address or dates of birth, or anything else.
- UNCERTAIN: use alone when the data does not let you tell.
Return every category the consumer actually disputes; most disputes have one. A supporting document (for example a bank statement) mentioning a balance does not by itself make the dispute about BALANCE. Base the categories on the text only; you are not shown the bureau's dispute code on purpose.
"confidence" is your probability (0 to 1) that the set is exactly right. It is logged for analysis and never used to make a decision. "rationale" is one short neutral sentence.

## user
Classify this dispute. The data blocks follow.
{{DATA}}
Return only the JSON object.
