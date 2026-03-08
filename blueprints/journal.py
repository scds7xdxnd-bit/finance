from flask import Blueprint, jsonify, request
from finance_app.lib.auth import csrf_token_valid, current_user
from ml.journal_model import JournalModel

journal_bp = Blueprint('journal_bp', __name__)

# Single shared model instance for simplicity. In production, consider app context or DI.
_model = JournalModel()


@journal_bp.route('/journal_feedback', methods=['POST'])
def journal_feedback():
    user = current_user()
    if not user:
        return jsonify({'ok': False, 'error': 'Unauthorized'}), 401
    if not csrf_token_valid():
        return jsonify({'ok': False, 'error': 'CSRF token missing or invalid'}), 400
    if not request.is_json:
        return jsonify({'ok': False, 'error': 'Expected application/json'}), 400
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify({'ok': False, 'error': 'Expected JSON object payload'}), 400
    # Basic validation
    if 'accepted' not in data or 'suggestion' not in data:
        return jsonify({'ok': False, 'error': 'Missing required fields "accepted" or "suggestion"'}), 400
    submitted_user_id = data.get('user_id')
    if submitted_user_id is None:
        data['user_id'] = int(user.id)
    else:
        try:
            submitted_user_id = int(submitted_user_id)
        except Exception:
            return jsonify({'ok': False, 'error': 'Invalid user_id'}), 400
        if submitted_user_id != int(user.id):
            return jsonify({'ok': False, 'error': 'Forbidden'}), 403
        data['user_id'] = submitted_user_id
    result = _model.update_with_feedback(data)
    if result.get('ok'):
        return jsonify({'ok': True})
    return jsonify({'ok': False, 'error': result.get('error', 'Unknown error')}), 500
