from flask import Blueprint, jsonify, request
from ml.journal_model import JournalModel

journal_bp = Blueprint('journal_bp', __name__)

# Single shared model instance for simplicity. In production, consider app context or DI.
_model = JournalModel()

@journal_bp.route('/journal_feedback', methods=['POST'])
def journal_feedback():
    if not request.is_json:
        return jsonify({'ok': False, 'error': 'Expected application/json'}), 400
    data = request.get_json()
    # Basic validation
    if 'accepted' not in data or 'suggestion' not in data:
        return jsonify({'ok': False, 'error': 'Missing required fields "accepted" or "suggestion"'}), 400
    result = _model.update_with_feedback(data)
    if result.get('ok'):
        return jsonify({'ok': True})
    return jsonify({'ok': False, 'error': result.get('error', 'Unknown error')}), 500
