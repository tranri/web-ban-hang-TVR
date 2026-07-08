/**
 * Password Strength Validator
 * Displays real-time feedback for password requirements
 */

document.addEventListener('DOMContentLoaded', function() {
    const passwordInput = document.getElementById('id_password');
    const passwordConfirmInput = document.getElementById('id_password_confirm');
    const requirementsContainer = document.getElementById('password-requirements');

    if (!passwordInput || !requirementsContainer) {
        return; // Exit if not on registration page
    }

    // Password requirement checks
    const requirements = {
        uppercase: {
            regex: /[A-Z]/,
            text: 'Chữ hoa (A-Z)',
            id: 'req-uppercase'
        },
        lowercase: {
            regex: /[a-z]/,
            text: 'Chữ thường (a-z)',
            id: 'req-lowercase'
        },
        number: {
            regex: /[0-9]/,
            text: 'Chữ số (0-9)',
            id: 'req-number'
        },
        special: {
            regex: /[@#$!%^&*()_+\-=\[\]{};':"\\|,.<>\/?]/,
            text: 'Ký tự đặc biệt (@, #, $, !, etc.)',
            id: 'req-special'
        },
        minLength: {
            check: (pwd) => pwd.length >= 8,
            text: 'Tối thiểu 8 ký tự',
            id: 'req-length'
        }
    };

    // Create HTML for requirements display
    function createRequirementsHTML() {
        let html = '<div class="password-requirements-box mt-3">';
        html += '<p class="fw-bold mb-2">📋 Yêu cầu mật khẩu:</p>';
        html += '<ul class="list-unstyled">';

        Object.keys(requirements).forEach(key => {
            const req = requirements[key];
            html += `<li class="mb-2">
                <span id="${req.id}" class="requirement-item" style="display: inline-flex; align-items: center; color: #ccc;">
                    <i class="fas fa-circle-xmark" style="margin-right: 8px; font-size: 14px;"></i>
                    ${req.text}
                </span>
            </li>`;
        });

        html += '</ul>';
        html += '</div>';

        if (passwordConfirmInput) {
            html += '<div class="password-match-box mt-3" id="password-match" style="display: none;">';
            html += '<p class="fw-bold mb-2">✓ Xác nhận mật khẩu:</p>';
            html += '<div id="match-feedback"></div>';
            html += '</div>';
        }

        return html;
    }

    // Insert requirements HTML after password input
    requirementsContainer.innerHTML = createRequirementsHTML();

    // Update requirement checks
    function updateRequirements(password) {
        let allMet = true;

        // Check uppercase
        const hasUppercase = requirements.uppercase.regex.test(password);
        updateRequirementItem('req-uppercase', hasUppercase);
        if (!hasUppercase) allMet = false;

        // Check lowercase
        const hasLowercase = requirements.lowercase.regex.test(password);
        updateRequirementItem('req-lowercase', hasLowercase);
        if (!hasLowercase) allMet = false;

        // Check number
        const hasNumber = requirements.number.regex.test(password);
        updateRequirementItem('req-number', hasNumber);
        if (!hasNumber) allMet = false;

        // Check special character
        const hasSpecial = requirements.special.regex.test(password);
        updateRequirementItem('req-special', hasSpecial);
        if (!hasSpecial) allMet = false;

        // Check minimum length
        const hasMinLength = requirements.minLength.check(password);
        updateRequirementItem('req-length', hasMinLength);
        if (!hasMinLength) allMet = false;

        return allMet;
    }

    // Update individual requirement item styling
    function updateRequirementItem(id, isMet) {
        const element = document.getElementById(id);
        if (!element) return;

        if (isMet) {
            element.style.color = '#28a745';
            element.innerHTML = element.innerHTML.replace(
                /fa-circle-xmark/,
                'fa-check-circle'
            );
        } else {
            element.style.color = '#ccc';
            element.innerHTML = element.innerHTML.replace(
                /fa-check-circle/,
                'fa-circle-xmark'
            );
        }
    }

    // Check password confirmation match
    function updatePasswordMatch() {
        if (!passwordConfirmInput) return;

        const password = passwordInput.value;
        const passwordConfirm = passwordConfirmInput.value;
        const matchFeedback = document.getElementById('match-feedback');

        if (passwordConfirm.length === 0) {
            document.getElementById('password-match').style.display = 'none';
            return;
        }

        document.getElementById('password-match').style.display = 'block';

        if (password === passwordConfirm) {
            matchFeedback.innerHTML = `
                <span style="color: #28a745; display: flex; align-items: center;">
                    <i class="fas fa-check-circle" style="margin-right: 8px; font-size: 18px;"></i>
                    Mật khẩu khớp ✓
                </span>
            `;
        } else {
            matchFeedback.innerHTML = `
                <span style="color: #dc3545; display: flex; align-items: center;">
                    <i class="fas fa-times-circle" style="margin-right: 8px; font-size: 18px;"></i>
                    Mật khẩu không khớp
                </span>
            `;
        }
    }

    // Event listeners
    passwordInput.addEventListener('input', function() {
        updateRequirements(this.value);
        updatePasswordMatch();
    });

    if (passwordConfirmInput) {
        passwordConfirmInput.addEventListener('input', updatePasswordMatch);
    }

    // Initial check
    updateRequirements(passwordInput.value);
});