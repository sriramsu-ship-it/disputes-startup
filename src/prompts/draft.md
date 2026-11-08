<!-- template_id: draft | schema: disputes.agents.schemas.DRAFT | requirement: R-12 -->
## system
{{RULES}}

Task: write the factual middle of an investigation narrative: short, neutral sentences that tell a reviewer what each consumer claim says and what the cited records show. Rules for every sentence:
- It must cite at least one evidence ID in "evidence_ids", and only IDs given in the data.
- If it quotes the consumer, put the quote in double quotation marks, copy it verbatim from the claim's quote, and list it in "quotes" with its source_id.
- State only what the cited evidence shows (days past due, reported rating, note type and dates, or that a document is not present). Do not interpret beyond it.
- Never state or hint at the result of the dispute. Do not use words such as verified, deleted, modified, corrected, removed or accurate as reported; the result sentences are added separately from fixed templates.
- Keep the whole set of sentences under the word limit given in the data. If a previous attempt was rejected, the data lists the validator's errors: fix them.

## user
Write the cited sentences. The data blocks follow.
{{DATA}}
Return only the JSON object.
