# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""Settings panel for the optional bring-your-own-key LLM.

Every value is a thin wrapper over an ir.config_parameter; the API key itself
is NOT stored here - it points at a vaulted eh.board.credential, so the secret
never lands in a plain config parameter or a settings export.
"""
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    eh_board_ai_provider = fields.Selection(
        [("off", "Off"), ("openai", "OpenAI-compatible"), ("anthropic", "Anthropic")],
        string="Dashboard AI provider", default="off",
        config_parameter="eh_board.ai_provider",
        help="Off by default. When set, the dashboard's Explain-with-AI button "
             "calls YOUR own endpoint with YOUR own key. No vendor proxy.")
    eh_board_ai_model = fields.Char(
        string="AI model", config_parameter="eh_board.ai_model",
        help="Model name, e.g. gpt-4o-mini or claude-3-5-haiku-latest.")
    eh_board_ai_base_url = fields.Char(
        string="AI base URL", config_parameter="eh_board.ai_base_url",
        help="Optional override for a self-hosted, Azure, or proxy endpoint. "
             "Leave blank for the provider default.")
    eh_board_ai_credential = fields.Char(
        string="AI credential name", config_parameter="eh_board.ai_credential",
        help="Name of the Dashboard Credential holding the API key. The key "
             "value stays in the vault and is never shown to non-administrators.")
    eh_board_ai_word_cap = fields.Integer(
        string="AI narrative word cap", default=180,
        config_parameter="eh_board.ai_word_cap",
        help="Maximum length of the generated executive narrative.")
    eh_board_ai_authoring_daily_requests = fields.Integer(
        string="AI authoring requests per user per day", default=20,
        config_parameter="eh_board.ai_authoring_daily_requests",
        help="Daily request limit for dashboard creation and refinement.")
    eh_board_ai_authoring_max_tokens = fields.Integer(
        string="AI authoring output token limit", default=1800,
        config_parameter="eh_board.ai_authoring_max_tokens",
        help="Maximum generated tokens per dashboard authoring request.")
