from .bug_reviewer import BUG_REVIEWER
from .performance_reviewer import PERFORMANCE_REVIEWER
from .security_reviewer import SECURITY_REVIEWER
from .style_reviewer import STYLE_REVIEWER

ALL_REVIEWERS = {
    "style": STYLE_REVIEWER,
    "bugs": BUG_REVIEWER,
    "security": SECURITY_REVIEWER,
    "performance": PERFORMANCE_REVIEWER,
}
