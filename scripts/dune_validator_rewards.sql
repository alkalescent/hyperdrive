-- Daily consensus and execution rewards for one Ethereum validator.
--
-- Dune query parameters:
--   validator_index (number)
--   fee_recipient   (text, 0x-prefixed execution address)
--   start_date      (date, inclusive UTC date)
--   end_date        (date, exclusive UTC date)
--
-- This query deliberately emits a row for every requested day, including
-- zero-reward days. DuneRewardProvider rejects the entire result if
-- any row has coverage_complete = false.

WITH
parameters AS (
    SELECT
        CAST('{{start_date}}' AS DATE) AS start_date,
        CAST('{{end_date}}' AS DATE) AS end_date,
        CAST({{validator_index}} AS BIGINT) AS validator_index,
        from_hex('{{fee_recipient}}') AS fee_recipient
),
days AS (
    SELECT day
    FROM parameters
    CROSS JOIN UNNEST(
        sequence(start_date, date_add('day', -1, end_date))
    ) AS generated(day)
),
consensus AS (
    SELECT
        summary.block_date AS day,
        summary.reward_change AS consensus_reward_gwei,
        summary.capital_change AS capital_change_gwei,
        summary.proposals_included
    FROM beacon.validator_day_summaries AS summary
    CROSS JOIN parameters
    WHERE summary.validator_index = parameters.validator_index
      AND summary.block_date >= parameters.start_date
      AND summary.block_date < parameters.end_date
),
proposal_blocks AS (
    SELECT
        beacon_block.date AS day,
        beacon_block.execution_payload_block_number AS block_number,
        beacon_block.execution_payload_block_hash AS block_hash,
        beacon_block.execution_payload_fee_recipient AS payload_fee_recipient,
        beacon_block.execution_payload_base_fee_per_gas AS base_fee_per_gas,
        parameters.fee_recipient,
        cardinality(beacon_block.execution_payload_transactions) AS expected_tx_count
    FROM beacon.blocks AS beacon_block
    CROSS JOIN parameters
    WHERE beacon_block.proposer_index = parameters.validator_index
      AND beacon_block.date >= parameters.start_date
      AND beacon_block.date < parameters.end_date
      AND beacon_block.finalized
      AND NOT beacon_block.execution_optimistic
),
transaction_rollup AS (
    SELECT
        proposal.block_number,
        count(tx.hash) AS transaction_count,
        coalesce(
            sum(
                CAST(
                    coalesce(
                        tx.priority_fee_per_gas,
                        greatest(tx.gas_price - proposal.base_fee_per_gas, 0)
                    ) AS UINT256
                )
                * CAST(tx.gas_used AS UINT256)
            ),
            UINT256 '0'
        ) AS priority_fee_wei
    FROM proposal_blocks AS proposal
    LEFT JOIN ethereum.transactions AS tx
      ON tx.block_number = proposal.block_number
     AND tx.block_hash = proposal.block_hash
     AND tx.block_date = proposal.day
     AND tx.block_date >= CAST('{{start_date}}' AS DATE)
     AND tx.block_date < CAST('{{end_date}}' AS DATE)
    GROUP BY proposal.block_number
),
trace_rollup AS (
    SELECT
        proposal.block_number,
        count(DISTINCT trace.tx_hash) AS traced_transaction_count,
        coalesce(
            sum(
                CASE
                    WHEN trace.success
                     AND trace.tx_success
                     AND trace.type = 'call'
                     AND trace.call_type = 'call'
                     AND trace."to" = proposal.fee_recipient
                     AND trace."from" <> proposal.fee_recipient
                        THEN trace.value
                    WHEN trace.success
                     AND trace.tx_success
                     AND trace.type = 'suicide'
                     AND trace.refund_address = proposal.fee_recipient
                     AND trace."from" <> proposal.fee_recipient
                        THEN trace.value
                    ELSE UINT256 '0'
                END
            ),
            UINT256 '0'
        ) AS recipient_transfers_wei
    FROM proposal_blocks AS proposal
    LEFT JOIN ethereum.traces AS trace
      ON trace.block_number = proposal.block_number
     AND trace.block_hash = proposal.block_hash
     AND trace.block_date = proposal.day
     AND trace.block_date >= CAST('{{start_date}}' AS DATE)
     AND trace.block_date < CAST('{{end_date}}' AS DATE)
    GROUP BY proposal.block_number
),
execution_blocks AS (
    SELECT
        proposal.day,
        proposal.block_number,
        CASE
            WHEN proposal.payload_fee_recipient = proposal.fee_recipient
                THEN tx_rollup.priority_fee_wei + trace.recipient_transfers_wei
            ELSE trace.recipient_transfers_wei
        END AS execution_reward_wei,
        tx_rollup.transaction_count = proposal.expected_tx_count
            AND trace.traced_transaction_count = proposal.expected_tx_count
            AND (
                proposal.payload_fee_recipient = proposal.fee_recipient
                OR trace.recipient_transfers_wei > UINT256 '0'
            ) AS block_complete
    FROM proposal_blocks AS proposal
    INNER JOIN transaction_rollup AS tx_rollup
      ON tx_rollup.block_number = proposal.block_number
    INNER JOIN trace_rollup AS trace
      ON trace.block_number = proposal.block_number
),
execution_daily AS (
    SELECT
        day,
        count(*) AS included_proposals,
        sum(execution_reward_wei) AS execution_reward_wei,
        bool_and(block_complete) AS blocks_complete
    FROM execution_blocks
    GROUP BY day
)
SELECT
    days.day,
    CAST(coalesce(consensus.consensus_reward_gwei, 0) AS VARCHAR)
        AS consensus_reward_gwei,
    CAST(coalesce(execution.execution_reward_wei, UINT256 '0') AS VARCHAR)
        AS execution_reward_wei,
    CAST(coalesce(consensus.capital_change_gwei, 0) AS VARCHAR)
        AS capital_change_gwei,
    consensus.day IS NOT NULL
        AND days.day < current_date
        AND coalesce(consensus.proposals_included, 0)
            = coalesce(execution.included_proposals, 0)
        AND coalesce(execution.blocks_complete, true)
        AS coverage_complete
FROM days
LEFT JOIN consensus ON consensus.day = days.day
LEFT JOIN execution_daily AS execution ON execution.day = days.day
ORDER BY days.day
