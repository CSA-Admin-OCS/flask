"""
=============================================================================
GEMINI AI API - Text Analysis & Citation Checking
=============================================================================
Google's Gemini API for AI-powered text analysis, citation checking, and
general language model tasks.

SETUP REQUIRED:
1. Get an API key from: https://aistudio.google.com/app/apikey
2. Add to your .env file:
   GEMINI_API_KEY=your_key_here
   GEMINI_SERVER=https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent

ENDPOINTS PROVIDED:
- POST /api/gemini         - Main text analysis (citation checking, custom prompts)
- GET  /api/gemini/health  - Health check and configuration status
- POST /api/gemini/debug   - Debug endpoint for troubleshooting API issues

AUTHENTICATION:
All endpoints require authentication via token (uses @token_required decorator).
Include your auth token in request headers.

DEFAULT BEHAVIOR:
- Default prompt performs academic citation analysis (APA format)
- Custom prompts can be provided via the 'prompt' field
- 90 second timeout for API requests

USAGE EXAMPLE (JavaScript frontend):
    fetch('/api/gemini', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'Authorization': 'Bearer your_token_here'
        },
        credentials: 'include',
        body: JSON.stringify({
            text: 'Your text to analyze here...',
            prompt: 'Optional custom prompt (defaults to citation analysis)'
        })
    })

RESPONSE FORMAT:
    Success: { "success": true, "text": "generated response", "user": "user_id" }
    Error:   { "message": "error description", "error_code": 500 }

ERROR CODES:
- 400: Bad request (missing text field or invalid input)
- 429: Rate limit exceeded
- 500: Server error or API configuration issue
- 503: Gemini API temporarily unavailable
=============================================================================
"""
from __init__ import app
from flask import Blueprint, request, jsonify, current_app, g
from flask_restful import Api, Resource
import requests
import time
import os
from api.authorize import token_required

MAX_GEMINI_RETRIES = 3
GEMINI_RETRY_STATUS_CODES = {429, 503}

# =============================================================================
# AUTH DECORATOR (DEV-ONLY BYPASS)
# =============================================================================

def require_auth_if_production(f):
    """
    Dev-only bypass: require auth only in production.
    In development (IS_PRODUCTION not set), endpoints are public.
    In production, endpoints require token_required() authentication.
    """
    is_production = os.environ.get('IS_PRODUCTION', 'false').lower() == 'true'
    if is_production:
        return token_required()(f)
    return f

# =============================================================================
# BLUEPRINT SETUP
# =============================================================================

gemini_api = Blueprint('gemini_api', __name__, url_prefix='/api')
api = Api(gemini_api)

# =============================================================================
# HELPERS
# =============================================================================

def analyze_log_text(log_text):
    """Send a Jekyll build log to Gemini and return the parsed response."""
    api_key = app.config.get('GEMINI_API_KEY')
    server = app.config.get('GEMINI_SERVER')

    if not api_key:
        return {'message': 'Gemini API key not configured'}, 500

    if not server:
        return {'message': 'Gemini server not configured'}, 500

    endpoint = f"{server}?key={api_key}"

    system_prompt = """
You are an AI assistant that analyzes Jekyll build logs.

Your job:
1. Determine whether the build succeeded or failed.
2. If it failed, identify the most likely cause.
3. Recommend what a student should do to fix the build or Makefile.
4. Do not print the full log contents.
5. Keep the answer concise and actionable.
"""

    log_text = log_text[-8000:]
    payload = {
        "contents": [{
            "parts": [{
                "text": f"{system_prompt}\n\n{log_text}"
            }]
        }]
    }

    current_app.logger.info("Gemini log analysis request made")

    try:
        for attempt in range(1, MAX_GEMINI_RETRIES + 1):
            response = requests.post(
                endpoint,
                headers={'Content-Type': 'application/json'},
                json=payload,
                timeout=90
            )

            if response.status_code == 200:
                break

            error_details = {
                'status_code': response.status_code,
                'response_text': response.text,
                'endpoint': endpoint,
                'headers': dict(response.headers)
            }
            current_app.logger.error(f"Gemini API error: {error_details}")

            # Retry on 429/503 if attempts remain
            if response.status_code in GEMINI_RETRY_STATUS_CODES and attempt < MAX_GEMINI_RETRIES:
                retry_after = response.headers.get('Retry-After')
                try:
                    wait_seconds = int(retry_after)
                except (TypeError, ValueError):
                    wait_seconds = 2 ** attempt

                current_app.logger.warning(
                    f"Gemini rate limited (status={response.status_code}); "
                    f"retry {attempt}/{MAX_GEMINI_RETRIES} in {wait_seconds}s"
                )
                time.sleep(wait_seconds)
                continue

            # All retries exhausted or non-retryable error
            if response.status_code == 503:
                return {
                    'message': 'Gemini API is temporarily unavailable (503). Please try again later.',
                    'error_code': 503,
                    'details': 'The service may be overloaded or under maintenance.'
                }, 503
            elif response.status_code == 429:
                return {
                    'message': 'Rate limit exceeded after retries. Please try again later.',
                    'error_code': 429
                }, 429
            elif response.status_code == 400:
                return {
                    'message': 'Bad request to Gemini API. Please check your input.',
                    'error_code': 400,
                    'details': response.text
                }, 400
            else:
                return {
                    'message': f'Gemini API error: {response.status_code}',
                    'error_code': response.status_code,
                    'details': response.text
                }, 500

        result = response.json()
        try:
            generated_text = result['candidates'][0]['content']['parts'][0]['text']
            return {
                'success': True,
                'analysis': generated_text.strip()
            }
        except (KeyError, IndexError) as e:
            current_app.logger.error(f"Error parsing Gemini response: {e}")
            return {
                'success': False,
                'message': 'Error parsing Gemini API response',
                'raw_response': result
            }, 500

    except requests.RequestException as e:
        current_app.logger.error(f"Error communicating with Gemini API: {e}")
        return {'message': f'Error communicating with Gemini API: {str(e)}'}, 500
    except Exception as e:
        current_app.logger.error(f"Unexpected error in log analysis: {e}")
        return {'message': f'Unexpected error: {str(e)}'}, 500

# =============================================================================
# ENDPOINTS
# =============================================================================

class GeminiAPI:
    class _Ask(Resource):
        """
        Main analysis endpoint - POST /api/gemini
        Handles text analysis with customizable prompts.
        Default: Academic citation checking (APA format).
        """
        @require_auth_if_production
        def post(self):
            """
            Send a request to the Gemini API.

            Expected JSON body:
            {
                "text": "Text to analyze",
                "prompt": "Optional custom prompt" (defaults to citation analysis)
            }

            Returns:
                JSON response from Gemini API or error message
            """
            current_user = g.current_user
            body = request.get_json()

            # Validate request body
            if not body:
                return {'message': 'Request body is required'}, 400

            text = body.get('text', '')
            if not text:
                return {'message': 'Text field is required'}, 400

            # Get configuration
            api_key = app.config.get('GEMINI_API_KEY')
            server = app.config.get('GEMINI_SERVER')

            if not api_key:
                return {'message': 'Gemini API key not configured'}, 500

            if not server:
                return {'message': 'Gemini server not configured'}, 500

            # Build the endpoint URL
            endpoint = f"{server}?key={api_key}"

            # Default prompt for citation analysis, can be overridden
            default_prompt = "Please look at this text for correct academic citations, and recommend APA references for each area of concern"
            prompt = body.get('prompt', default_prompt)

            # Prepare the request payload for Gemini API
            payload = {
                "contents": [{
                    "parts": [{
                        "text": f"{prompt}: {text}"
                    }]
                }]
            }

            # Log the request for auditing purposes
            current_app.logger.info(f"User {current_user.uid} made a Gemini API request")

            try:
                current_app.logger.info(f"Making request to Gemini API: {endpoint}")
                current_app.logger.debug(f"Payload: {payload}")

                response = requests.post(
                    endpoint,
                    headers={'Content-Type': 'application/json'},
                    json=payload,
                    timeout=90
                )

                if response.status_code != 200:
                    error_details = {
                        'status_code': response.status_code,
                        'response_text': response.text,
                        'endpoint': endpoint,
                        'headers': dict(response.headers)
                    }
                    current_app.logger.error(f"Gemini API error: {error_details}")

                    if response.status_code == 503:
                        return {
                            'message': 'Gemini API is temporarily unavailable (503). Please try again later.',
                            'error_code': 503,
                            'details': 'The service may be overloaded or under maintenance.'
                        }, 503
                    elif response.status_code == 429:
                        return {
                            'message': 'Rate limit exceeded. Please try again later.',
                            'error_code': 429
                        }, 429
                    elif response.status_code == 400:
                        return {
                            'message': 'Bad request to Gemini API. Please check your input.',
                            'error_code': 400,
                            'details': response.text
                        }, 400
                    else:
                        return {
                            'message': f'Gemini API error: {response.status_code}',
                            'error_code': response.status_code,
                            'details': response.text
                        }, 500

                result = response.json()

                try:
                    generated_text = result['candidates'][0]['content']['parts'][0]['text']
                    return {
                        'success': True,
                        'text': generated_text,
                        'user': current_user.uid
                    }
                except (KeyError, IndexError) as e:
                    current_app.logger.error(f"Error parsing Gemini response: {e}")
                    return {
                        'success': False,
                        'message': 'Error parsing Gemini API response',
                        'raw_response': result
                    }, 500

            except requests.RequestException as e:
                current_app.logger.error(f"Error communicating with Gemini API: {e}")
                return {'message': f'Error communicating with Gemini API: {str(e)}'}, 500
            except Exception as e:
                current_app.logger.error(f"Unexpected error in Gemini API: {e}")
                return {'message': f'Unexpected error: {str(e)}'}, 500

    class _Health(Resource):
        """
        Health check - GET /api/gemini/health
        Verifies API configuration and tests connectivity.
        """
        @require_auth_if_production
        def get(self):
            """
            Check if Gemini API is properly configured.

            Returns:
                JSON response indicating configuration status
            """
            api_key = app.config.get('GEMINI_API_KEY')
            server = app.config.get('GEMINI_SERVER')

            status_info = {
                'gemini_configured': bool(api_key and server),
                'server': server if server else 'Not configured',
                'api_key_present': bool(api_key)
            }

            if api_key and server:
                try:
                    test_endpoint = f"{server}?key={api_key}"
                    test_payload = {
                        "contents": [{
                            "parts": [{"text": "Hello"}]
                        }]
                    }

                    response = requests.post(
                        test_endpoint,
                        headers={'Content-Type': 'application/json'},
                        json=test_payload,
                        timeout=10
                    )

                    status_info['api_test'] = {
                        'status_code': response.status_code,
                        'available': response.status_code == 200
                    }

                    if response.status_code != 200:
                        status_info['api_test']['error'] = response.text

                except Exception as e:
                    status_info['api_test'] = {
                        'available': False,
                        'error': str(e)
                    }

            return status_info

    class _LogAnalyzer(Resource):
        """
        Log analysis endpoint - POST /api/gemini/analyze-log
        Analyzes Jekyll build logs using AI.
        """
        @require_auth_if_production
        def post(self):
            """
            Analyze a Jekyll build log.

            Expected JSON body:
            {
                "log": "The log content to analyze"
            }

            Returns:
                JSON response with analysis or error message
            """
            body = request.get_json()

            if not body:
                return {'message': 'Request body is required'}, 400

            log = body.get('log', '')
            if not log:
                return {'message': 'Log field is required'}, 400

            return analyze_log_text(log)

    class _LogUpload(Resource):
        """
        File upload endpoint - POST /api/gemini/upload
        Accepts a file and analyzes its contents as a Jekyll build log.
        """
        @require_auth_if_production
        def post(self):
            if 'file' not in request.files:
                return {'message': 'File is required'}, 400

            file = request.files['file']
            if file.filename == '':
                return {'message': 'File name is required'}, 400

            try:
                content = file.read().decode('utf-8', errors='replace')
            except Exception as e:
                current_app.logger.error(f"Failed to read uploaded file: {e}")
                return {'message': f'File processing failed: {str(e)}'}, 400

            return analyze_log_text(content)

    class _Debug(Resource):
        """
        Debug endpoint to help troubleshoot Gemini API issues.
        """
        @require_auth_if_production
        def post(self):
            """
            Debug the Gemini API request to identify 503 issues.

            Returns detailed information about the request and response.
            """
            current_user = g.current_user
            body = request.get_json()

            api_key = app.config.get('GEMINI_API_KEY')
            server = app.config.get('GEMINI_SERVER')

            debug_info = {
                'user': current_user.uid,
                'config_check': {
                    'api_key_present': bool(api_key),
                    'api_key_length': len(api_key) if api_key else 0,
                    'server': server,
                    'server_valid': bool(server and server.startswith('https://'))
                },
                'request_body': body
            }

            if not api_key or not server:
                debug_info['error'] = 'Missing API configuration'
                return debug_info, 500

            endpoint = f"{server}?key={api_key}"
            debug_info['endpoint'] = endpoint

            test_payload = {
                "contents": [{
                    "parts": [{"text": "Test"}]
                }]
            }

            try:
                response = requests.post(
                    endpoint,
                    headers={'Content-Type': 'application/json'},
                    json=test_payload,
                    timeout=30
                )

                debug_info['response'] = {
                    'status_code': response.status_code,
                    'headers': dict(response.headers),
                    'content': response.text[:500] if response.text else None
                }

                return debug_info

            except Exception as e:
                debug_info['exception'] = str(e)
                return debug_info, 500

    # Register all endpoints
    api.add_resource(_Ask, '/gemini')                        # Main analysis endpoint
    api.add_resource(_Health, '/gemini/health')              # Health check
    api.add_resource(_Debug, '/gemini/debug')                # Debug/troubleshooting
    api.add_resource(_LogAnalyzer, '/gemini/analyze-log')    # Log analysis endpoint
    api.add_resource(_LogUpload, '/gemini/upload')           # File upload log analysis endpoint