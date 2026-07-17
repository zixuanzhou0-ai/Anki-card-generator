from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit


ROOT = Path(__file__).resolve().parents[1]
WORKERS = ROOT / 'workers'
if str(WORKERS) not in sys.path:
    sys.path.insert(0, str(WORKERS))

from acg.commands import generate_cards_from_learning_points as command  # noqa: E402


CANARY = 'PROJECT_RESULT_SECRET_CANARY'


def _point(point_id: str = 'lp-1') -> dict:
    return {
        'id': point_id,
        'source_segment_id': 'src-1',
        'source_sentence': 'Can you run the register for a minute?',
        'source_time': '00:00:10.000 - 00:00:12.000',
        'start': 10.0,
        'end': 12.0,
        'exact_span': 'run the register',
        'answer_core': 'run the register',
        'candidate_kind': 'expression',
        'phrase_type': 'collocation',
        'learning_action': 'Train the service-industry collocation.',
        'value_score': 4.8,
        'status': 'recommended',
    }


def _card(point_id: str = 'lp-1') -> dict:
    return {
        'id': f'card-{point_id}',
        'type': 'phrase',
        'enabled': True,
        'learning_point_id': point_id,
        'phrase': 'run the register',
        'answer_core': 'run the register',
        'english': 'Can you run the register for a minute?',
        'chinese': '你能帮忙收银一会儿吗？',
        'definition': 'Operate or take responsibility for the cash register.',
        'collocations': 'run the register / cover the register',
        'context': 'Can you run the register for a minute?',
        'example': 'I can run the register while you take inventory.',
        'chinese_feel': '用于服务业工作分工。',
        'teacher_note': 'Register means cash register in this context.',
        'why': 'A common workplace collocation.',
        'how_to_use_it': 'Use it when assigning checkout duty.',
        'usage_boundary': 'It does not mean running physically.',
    }


def _secret_url() -> str:
    return (
        'https://alice:password@www.youtube.com/watch'
        f'?v=video123&list=playlist456&t=42&api_key={CANARY}&access_token={CANARY}&foo=kept'
    )


def _secret_protocol_relative_url() -> str:
    return _secret_url().removeprefix('https:')


def _assert_no_canary(test_case: unittest.TestCase, project: dict) -> None:
    test_case.assertNotIn(CANARY, json.dumps(project, ensure_ascii=False, default=str))


def _assert_youtube_url_sanitized(test_case: unittest.TestCase, value: str) -> None:
    parsed = urlsplit(value)
    query = parse_qs(parsed.query, keep_blank_values=True)
    test_case.assertIsNone(parsed.username)
    test_case.assertIsNone(parsed.password)
    test_case.assertEqual(parsed.hostname, 'www.youtube.com')
    test_case.assertEqual(query['v'], ['video123'])
    test_case.assertEqual(query['list'], ['playlist456'])
    test_case.assertEqual(query['t'], ['42'])
    test_case.assertEqual(query['foo'], ['kept'])
    test_case.assertNotIn('api_key', query)
    test_case.assertNotIn('access_token', query)


class ProjectResultSecretScrubTests(unittest.TestCase):
    def _base_payload(self) -> dict:
        return {
            'project_id': 'project-secret-scrub',
            'title': 'Secret scrub',
            'language': 'en',
            'level': 'B1',
            'disable_card_generation_cache': True,
            'api_config': {
                'provider': 'openai-compatible',
                'model': 'test-model',
                'api_key': CANARY,
                'credential_revision': 7,
                'client_secret_ref': 'keyring://model/test',
                'has_api_key': True,
            },
            'tts_config': {
                'api_key': CANARY,
                'nested': {'refresh_token': CANARY},
            },
            'card_types': ['phrase'],
        }

    def test_normal_handler_result_scrubs_all_nested_project_surfaces(self) -> None:
        payload = {
            **self._base_payload(),
            'source_url': _secret_url(),
            'source_info': {
                'page_url': _secret_url(),
                'protocol_relative_url': _secret_protocol_relative_url(),
                'private_key': CANARY,
                'deep': {'Authorization': f'Bearer {CANARY}'},
            },
            'batch_enabled': True,
            'batch_items': [
                {
                    'source_url': _secret_url(),
                    'cookie': CANARY,
                    'deep': [{'client_secret': CANARY}],
                }
            ],
            'tts_semantic_verification': {
                'status': 'passed',
                'access_token': CANARY,
                'evidence': [{'password': CANARY}],
            },
            'selected_learning_point_ids': ['lp-1'],
            'learning_points': [_point()],
        }
        ai_payload = {
            'segments': [
                {
                    'id': 'seg_lp_0001',
                    'cards': [_card()],
                }
            ]
        }
        with (
            patch.object(command.legacy_worker, 'phrase_review_available', return_value=True),
            patch.object(
                command,
                '_cached_or_generated_card_payload',
                return_value=(ai_payload, {'cache_hits': 0, 'cache_misses': 1}),
            ),
        ):
            project = command.handle_generate_cards_from_learning_points(payload)

        _assert_no_canary(self, project)
        _assert_youtube_url_sanitized(self, project['source_url'])
        _assert_youtube_url_sanitized(self, project['source_info']['page_url'])
        _assert_youtube_url_sanitized(self, project['source_info']['protocol_relative_url'])
        _assert_youtube_url_sanitized(self, project['batch_items'][0]['source_url'])
        self.assertEqual(project['api_config']['api_key'], '')
        self.assertEqual(project['source_info']['private_key'], '')
        self.assertEqual(project['batch_items'][0]['cookie'], '')
        self.assertEqual(project['tts_semantic_verification']['access_token'], '')
        self.assertEqual(project['api_config']['credential_revision'], 7)
        self.assertEqual(project['api_config']['client_secret_ref'], 'keyring://model/test')
        self.assertIs(project['api_config']['has_api_key'], True)

    def test_existing_project_fast_path_scrubs_spread_and_override_fields(self) -> None:
        payload = {
            **self._base_payload(),
            'selected_learning_point_ids': ['lp-1'],
            'learning_points': [_point()],
            'tts_semantic_verification': {
                'enabled': True,
                'oauth_token': CANARY,
                'deep': {'password': CANARY},
            },
            'existing_project': {
                'id': 'project-secret-scrub',
                'title': 'Existing project',
                'access_token': CANARY,
                'source_url': _secret_url(),
                'source_info': {
                    'page_url': _secret_url(),
                    'deep': {'client_secret': CANARY},
                },
                'batch_items': [{'session_token': CANARY}],
                'custom': {'nested': [{'private_key': CANARY}]},
                'segments': [
                    {
                        'id': 'seg_lp_0001',
                        'learning_point_id': 'lp-1',
                        'text': 'Can you run the register for a minute?',
                        'cards': [{**_card(), 'nested': {'cookie': CANARY}}],
                    }
                ],
            },
        }
        with patch.object(command.legacy_worker, 'phrase_review_available', return_value=True):
            project = command.handle_generate_cards_from_learning_points(payload)

        _assert_no_canary(self, project)
        _assert_youtube_url_sanitized(self, project['source_url'])
        _assert_youtube_url_sanitized(self, project['source_info']['page_url'])
        self.assertEqual(project['access_token'], '')
        self.assertEqual(project['source_info']['deep']['client_secret'], '')
        self.assertEqual(project['batch_items'][0]['session_token'], '')
        self.assertEqual(project['custom']['nested'][0]['private_key'], '')
        self.assertEqual(project['segments'][0]['cards'][0]['nested']['cookie'], '')
        self.assertEqual(project['tts_semantic_verification']['oauth_token'], '')

    def test_empty_result_path_scrubs_source_info_and_preserves_safe_metadata(self) -> None:
        payload = {
            **self._base_payload(),
            'source_url': _secret_url(),
            'source_info': {
                'page_url': _secret_url(),
                'api_key': CANARY,
                'nested': {'Authorization': CANARY},
                'credential_revision': 11,
                'client_secret_ref': 'keyring://empty/test',
                'has_api_key': True,
            },
            'selected_learning_point_ids': ['missing-learning-point'],
            'learning_points': [],
        }
        with patch.object(command.legacy_worker, 'phrase_review_available', return_value=True):
            project = command.handle_generate_cards_from_learning_points(payload)

        self.assertEqual(project['segments'], [])
        _assert_no_canary(self, project)
        _assert_youtube_url_sanitized(self, project['source_url'])
        _assert_youtube_url_sanitized(self, project['source_info']['page_url'])
        self.assertEqual(project['source_info']['api_key'], '')
        self.assertEqual(project['source_info']['nested']['Authorization'], '')
        self.assertEqual(project['source_info']['credential_revision'], 11)
        self.assertEqual(project['source_info']['client_secret_ref'], 'keyring://empty/test')
        self.assertIs(project['source_info']['has_api_key'], True)


if __name__ == '__main__':
    unittest.main()
