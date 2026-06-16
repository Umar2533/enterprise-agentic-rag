import 'package:flutter/material.dart';

import '../../../core/constants/api_constants.dart';
import '../../../core/network/api_client.dart';
import '../../../core/storage/app_session.dart';
import '../../../features/auth/data/services/auth_api_service.dart';
import '../../../features/chat/data/services/chat_api_service.dart';
import '../../../shared/widgets/app_card.dart';
import '../../../shared/widgets/status_badge.dart';

class SettingsScreen extends StatefulWidget {
  const SettingsScreen({required this.session, super.key});

  final AppSession session;

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  late final TextEditingController _urlController;
  late final TextEditingController _emailController;
  late final TextEditingController _passwordController;
  late final TextEditingController _signupFullNameController;
  late final TextEditingController _signupEmailController;
  late final TextEditingController _signupPasswordController;
  late final TextEditingController _verificationTokenController;
  late final TextEditingController _forgotEmailController;
  late final TextEditingController _resetTokenController;
  late final TextEditingController _resetPasswordController;
  late final TextEditingController _jwtTokenController;
  late final TextEditingController _apiKeyController;
  late final TextEditingController _openAiApiKeyController;
  late final TextEditingController _tavilyApiKeyController;
  String? _credentialMessage;
  String? _loginMessage;
  bool _loggingIn = false;
  String? _signupMessage;
  bool _signingUp = false;
  String? _verificationMessage;
  bool _verifyingEmail = false;
  String? _forgotPasswordMessage;
  bool _requestingPasswordReset = false;
  String? _resetPasswordMessage;
  bool _resettingPassword = false;
  String? _healthMessage;
  bool _checking = false;
  _AccountPanel _accountPanel = _AccountPanel.login;
  bool _advancedCredentialsExpanded = false;
  bool _loginPasswordVisible = false;
  bool _signupPasswordVisible = false;
  bool _resetPasswordVisible = false;

  @override
  void initState() {
    super.initState();
    _urlController = TextEditingController(text: widget.session.backendUrl);
    _emailController = TextEditingController();
    _passwordController = TextEditingController();
    _signupFullNameController = TextEditingController();
    _signupEmailController = TextEditingController();
    _signupPasswordController = TextEditingController();
    _verificationTokenController = TextEditingController();
    _forgotEmailController = TextEditingController();
    _resetTokenController = TextEditingController();
    _resetPasswordController = TextEditingController();
    _jwtTokenController = TextEditingController(text: widget.session.jwtToken);
    _apiKeyController = TextEditingController(text: widget.session.apiKey);
    _openAiApiKeyController = TextEditingController(
      text: widget.session.openAiApiKey,
    );
    _tavilyApiKeyController = TextEditingController(
      text: widget.session.tavilyApiKey,
    );
  }

  @override
  void dispose() {
    _urlController.dispose();
    _emailController.dispose();
    _passwordController.dispose();
    _signupFullNameController.dispose();
    _signupEmailController.dispose();
    _signupPasswordController.dispose();
    _verificationTokenController.dispose();
    _forgotEmailController.dispose();
    _resetTokenController.dispose();
    _resetPasswordController.dispose();
    _jwtTokenController.dispose();
    _apiKeyController.dispose();
    _openAiApiKeyController.dispose();
    _tavilyApiKeyController.dispose();
    super.dispose();
  }

  Future<void> _saveAuthCredentials() async {
    await widget.session.setJwtToken(_jwtTokenController.text);
    await widget.session.setApiKey(_apiKeyController.text);
    await widget.session.setOpenAiApiKey(_openAiApiKeyController.text);
    await widget.session.setTavilyApiKey(_tavilyApiKeyController.text);
    if (mounted) {
      setState(() {
        _credentialMessage = widget.session.hasActiveOpenAiKey
            ? 'OpenAI Runtime Key Active'
            : 'OpenAI Runtime Key Missing';
      });
    }
  }

  Future<void> _login() async {
    final email = _emailController.text.trim();
    final password = _passwordController.text;
    if (email.isEmpty || password.isEmpty) {
      setState(() {
        _loginMessage = 'Email and password are required.';
      });
      return;
    }

    await widget.session.setBackendUrl(_urlController.text);
    setState(() {
      _loggingIn = true;
      _loginMessage = null;
    });
    try {
      final service = AuthApiService(baseUrl: widget.session.backendUrl);
      final accessToken = await service.login(email: email, password: password);
      await widget.session.setJwtToken(accessToken);
      _jwtTokenController.text = accessToken;
      _emailController.clear();
      _passwordController.clear();
      if (mounted) {
        setState(() {
          _loggingIn = false;
          _loginMessage = 'Login successful. JWT saved for protected requests.';
        });
      }
    } catch (error) {
      if (mounted) {
        setState(() {
          _loggingIn = false;
          _loginMessage = error.toString();
        });
      }
    }
  }

  Future<void> _signup() async {
    final email = _signupEmailController.text.trim();
    final password = _signupPasswordController.text;
    if (email.isEmpty || password.isEmpty) {
      setState(() {
        _signupMessage = 'Email and password are required.';
      });
      return;
    }

    await widget.session.setBackendUrl(_urlController.text);
    setState(() {
      _signingUp = true;
      _signupMessage = null;
    });
    try {
      final service = AuthApiService(baseUrl: widget.session.backendUrl);
      final result = await service.signup(
        email: email,
        password: password,
        fullName: _signupFullNameController.text,
      );
      _signupFullNameController.clear();
      _signupEmailController.clear();
      _signupPasswordController.clear();
      if (mounted) {
        setState(() {
          _signingUp = false;
          _signupMessage = result.verificationHint == null
              ? result.message
              : '${result.message}\n${result.verificationHint}';
        });
      }
    } catch (error) {
      if (mounted) {
        setState(() {
          _signingUp = false;
          _signupMessage = error.toString();
        });
      }
    }
  }

  Future<void> _forgotPassword() async {
    final email = _forgotEmailController.text.trim();
    if (email.isEmpty) {
      setState(() {
        _forgotPasswordMessage = 'Email is required.';
      });
      return;
    }

    await widget.session.setBackendUrl(_urlController.text);
    setState(() {
      _requestingPasswordReset = true;
      _forgotPasswordMessage = null;
    });
    try {
      final service = AuthApiService(baseUrl: widget.session.backendUrl);
      final message = await service.forgotPassword(email: email);
      _forgotEmailController.clear();
      if (mounted) {
        setState(() {
          _requestingPasswordReset = false;
          _forgotPasswordMessage = message;
        });
      }
    } catch (error) {
      if (mounted) {
        setState(() {
          _requestingPasswordReset = false;
          _forgotPasswordMessage = error.toString();
        });
      }
    }
  }

  Future<void> _verifyEmail() async {
    final token = _verificationTokenController.text.trim();
    if (token.isEmpty) {
      setState(() {
        _verificationMessage = 'Verification token is required.';
      });
      return;
    }

    await widget.session.setBackendUrl(_urlController.text);
    setState(() {
      _verifyingEmail = true;
      _verificationMessage = null;
    });
    try {
      final service = AuthApiService(baseUrl: widget.session.backendUrl);
      final message = await service.verifyEmail(token: token);
      _verificationTokenController.clear();
      if (mounted) {
        setState(() {
          _verifyingEmail = false;
          _verificationMessage = message;
        });
      }
    } catch (error) {
      if (mounted) {
        setState(() {
          _verifyingEmail = false;
          _verificationMessage = error.toString();
        });
      }
    }
  }

  Future<void> _resetPassword() async {
    final token = _resetTokenController.text.trim();
    final password = _resetPasswordController.text;
    if (token.isEmpty || password.isEmpty) {
      setState(() {
        _resetPasswordMessage = 'Reset token and new password are required.';
      });
      return;
    }

    await widget.session.setBackendUrl(_urlController.text);
    setState(() {
      _resettingPassword = true;
      _resetPasswordMessage = null;
    });
    try {
      final service = AuthApiService(baseUrl: widget.session.backendUrl);
      final message = await service.resetPassword(
        token: token,
        newPassword: password,
      );
      _resetTokenController.clear();
      _resetPasswordController.clear();
      if (mounted) {
        setState(() {
          _resettingPassword = false;
          _resetPasswordMessage = message;
        });
      }
    } catch (error) {
      if (mounted) {
        setState(() {
          _resettingPassword = false;
          _resetPasswordMessage = error.toString();
        });
      }
    }
  }

  Future<void> _logout() async {
    await widget.session.setJwtToken(null);
    _jwtTokenController.clear();
    if (mounted) {
      setState(() {
        _loginMessage = 'Logged out locally.';
      });
    }
  }

  Future<void> _testHealth() async {
    await widget.session.setBackendUrl(_urlController.text);
    setState(() {
      _checking = true;
      _healthMessage = null;
    });
    try {
      final service = ChatApiService(
        baseUrl: widget.session.backendUrl,
        apiClient: ApiClient(debugMode: widget.session.debugMode),
      );
      final health = await service.checkHealth();
      if (mounted) {
        setState(() {
          _checking = false;
          _healthMessage =
              '${health.app} online. Vector DB: ${health.vectorDbProvider}. Embedding: ${health.embeddingProvider}.';
        });
      }
    } catch (error) {
      if (mounted) {
        setState(() {
          _checking = false;
          _healthMessage = error.toString();
        });
      }
    }
  }

  Widget _buildAccountSection(BuildContext context) {
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;
    final hasJwt = widget.session.jwtToken?.trim().isNotEmpty == true;

    return AppCard(
      padding: EdgeInsets.zero,
      child: DecoratedBox(
        decoration: BoxDecoration(
          gradient: LinearGradient(
            begin: Alignment.topLeft,
            end: Alignment.bottomRight,
            colors: [
              scheme.primaryContainer.withValues(alpha: .20),
              theme.cardColor,
              theme.cardColor,
            ],
            stops: const [0, .28, 1],
          ),
          borderRadius: BorderRadius.circular(14),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(18, 18, 18, 16),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Container(
                    width: 42,
                    height: 42,
                    decoration: BoxDecoration(
                      color: scheme.primaryContainer.withValues(alpha: .68),
                      borderRadius: BorderRadius.circular(13),
                    ),
                    child: Icon(
                      Icons.account_circle_outlined,
                      color: scheme.primary,
                    ),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          'Account',
                          style: theme.textTheme.titleLarge?.copyWith(
                            fontWeight: FontWeight.w900,
                          ),
                        ),
                        const SizedBox(height: 3),
                        Text(
                          'Sign in or manage account access for protected requests.',
                          style: theme.textTheme.bodySmall?.copyWith(
                            color: scheme.onSurfaceVariant,
                          ),
                        ),
                        const SizedBox(height: 9),
                        Wrap(
                          spacing: 8,
                          runSpacing: 8,
                          crossAxisAlignment: WrapCrossAlignment.center,
                          children: [
                            Container(
                              padding: const EdgeInsets.symmetric(
                                horizontal: 10,
                                vertical: 7,
                              ),
                              decoration: BoxDecoration(
                                color: hasJwt
                                    ? const Color(0xFFEAF8EF)
                                    : scheme.surfaceContainerHighest,
                                border: Border.all(
                                  color: hasJwt
                                      ? const Color(0xFFB7E4C7)
                                      : theme.dividerColor,
                                ),
                                borderRadius: BorderRadius.circular(999),
                              ),
                              child: Row(
                                mainAxisSize: MainAxisSize.min,
                                children: [
                                  Icon(
                                    hasJwt
                                        ? Icons.check_circle_rounded
                                        : Icons.lock_open_rounded,
                                    size: 15,
                                    color: hasJwt
                                        ? const Color(0xFF287A4B)
                                        : scheme.onSurfaceVariant,
                                  ),
                                  const SizedBox(width: 6),
                                  Text(
                                    hasJwt ? 'Signed in' : 'Signed out',
                                    style: theme.textTheme.labelMedium
                                        ?.copyWith(
                                          color: hasJwt
                                              ? const Color(0xFF287A4B)
                                              : scheme.onSurfaceVariant,
                                          fontWeight: FontWeight.w800,
                                        ),
                                  ),
                                ],
                              ),
                            ),
                            if (hasJwt)
                              OutlinedButton.icon(
                                onPressed: _logout,
                                icon: const Icon(
                                  Icons.logout_rounded,
                                  size: 17,
                                ),
                                label: const Text('Logout'),
                                style: OutlinedButton.styleFrom(
                                  minimumSize: const Size(0, 36),
                                  padding: const EdgeInsets.symmetric(
                                    horizontal: 12,
                                  ),
                                  foregroundColor: scheme.onSurface,
                                  backgroundColor: theme.cardColor.withValues(
                                    alpha: .84,
                                  ),
                                ),
                              ),
                          ],
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
            Divider(height: 1, color: theme.dividerColor),
            Padding(
              padding: const EdgeInsets.fromLTRB(18, 16, 18, 20),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  _buildAccountTabs(context),
                  const SizedBox(height: 22),
                  AnimatedSwitcher(
                    duration: const Duration(milliseconds: 200),
                    switchInCurve: Curves.easeOutCubic,
                    switchOutCurve: Curves.easeInCubic,
                    child: KeyedSubtree(
                      key: ValueKey(_accountPanel),
                      child: switch (_accountPanel) {
                        _AccountPanel.login => _buildLoginPanel(context),
                        _AccountPanel.signup => _buildSignupPanel(context),
                        _AccountPanel.verify => _buildVerifyPanel(context),
                        _AccountPanel.reset => _buildResetPanel(context),
                      },
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildAccountTabs(BuildContext context) {
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;

    return LayoutBuilder(
      builder: (context, constraints) {
        const spacing = 10.0;
        final columns = constraints.maxWidth < 600 ? 2 : 4;
        final innerWidth = constraints.maxWidth;
        final tabWidth = (innerWidth - (spacing * (columns - 1))) / columns;

        return Wrap(
          spacing: spacing,
          runSpacing: spacing,
          children: _AccountPanel.values.map((panel) {
            final selected = panel == _accountPanel;
            return SizedBox(
              width: tabWidth,
              child: AnimatedContainer(
                duration: const Duration(milliseconds: 170),
                curve: Curves.easeOutCubic,
                decoration: BoxDecoration(
                  color: selected
                      ? scheme.primaryContainer.withValues(alpha: .78)
                      : theme.cardColor.withValues(alpha: .88),
                  borderRadius: BorderRadius.circular(14),
                  border: Border.all(
                    color: selected
                        ? scheme.primary.withValues(alpha: .58)
                        : theme.dividerColor,
                    width: selected ? 1.4 : 1,
                  ),
                  boxShadow: selected
                      ? [
                          BoxShadow(
                            color: scheme.primary.withValues(alpha: .16),
                            blurRadius: 16,
                            offset: const Offset(0, 6),
                          ),
                        ]
                      : const [],
                ),
                child: Material(
                  color: Colors.transparent,
                  borderRadius: BorderRadius.circular(14),
                  child: InkWell(
                    onTap: () {
                      FocusScope.of(context).unfocus();
                      setState(() => _accountPanel = panel);
                    },
                    borderRadius: BorderRadius.circular(14),
                    hoverColor: scheme.primary.withValues(alpha: .07),
                    splashColor: scheme.primary.withValues(alpha: .10),
                    child: Padding(
                      padding: const EdgeInsets.symmetric(
                        horizontal: 10,
                        vertical: 13,
                      ),
                      child: Row(
                        mainAxisAlignment: MainAxisAlignment.center,
                        children: [
                          Icon(
                            panel.icon,
                            size: 18,
                            color: selected
                                ? scheme.primary
                                : scheme.onSurfaceVariant,
                          ),
                          const SizedBox(width: 7),
                          Flexible(
                            child: Text(
                              panel.label,
                              textAlign: TextAlign.center,
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                              style: theme.textTheme.labelLarge?.copyWith(
                                color: selected
                                    ? scheme.primary
                                    : scheme.onSurfaceVariant,
                                fontWeight: selected
                                    ? FontWeight.w900
                                    : FontWeight.w700,
                              ),
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),
                ),
              ),
            );
          }).toList(),
        );
      },
    );
  }

  Widget _buildPanelIntro(
    BuildContext context, {
    required String title,
    required String description,
  }) {
    final theme = Theme.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          title,
          style: theme.textTheme.titleMedium?.copyWith(
            fontWeight: FontWeight.w900,
          ),
        ),
        const SizedBox(height: 4),
        Text(
          description,
          style: theme.textTheme.bodySmall?.copyWith(
            color: theme.colorScheme.onSurfaceVariant,
          ),
        ),
      ],
    );
  }

  Widget _buildLoginPanel(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _buildPanelIntro(
          context,
          title: 'Welcome back',
          description: 'Use your verified account to save a JWT locally.',
        ),
        const SizedBox(height: 16),
        TextField(
          controller: _emailController,
          decoration: const InputDecoration(
            labelText: 'Email address',
            prefixIcon: Icon(Icons.email_outlined),
          ),
          keyboardType: TextInputType.emailAddress,
          textInputAction: TextInputAction.next,
          autocorrect: false,
        ),
        const SizedBox(height: 12),
        TextField(
          controller: _passwordController,
          decoration: InputDecoration(
            labelText: 'Password',
            prefixIcon: const Icon(Icons.lock_outline_rounded),
            suffixIcon: IconButton(
              onPressed: () {
                setState(() => _loginPasswordVisible = !_loginPasswordVisible);
              },
              icon: Icon(
                _loginPasswordVisible
                    ? Icons.visibility_off_outlined
                    : Icons.visibility_outlined,
              ),
              tooltip: _loginPasswordVisible
                  ? 'Hide password'
                  : 'Show password',
            ),
          ),
          obscureText: !_loginPasswordVisible,
          enableSuggestions: false,
          autocorrect: false,
          textInputAction: TextInputAction.done,
          onSubmitted: (_) {
            if (!_loggingIn) {
              _login();
            }
          },
        ),
        const SizedBox(height: 14),
        SizedBox(
          width: double.infinity,
          child: FilledButton.icon(
            onPressed: _loggingIn ? null : _login,
            icon: _loggingIn
                ? const SizedBox(
                    width: 18,
                    height: 18,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Icon(Icons.login_rounded),
            label: const Text('Login'),
          ),
        ),
        if (_loginMessage != null) ...[
          const SizedBox(height: 12),
          _AuthFeedback(message: _loginMessage!),
        ],
      ],
    );
  }

  Widget _buildSignupPanel(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _buildPanelIntro(
          context,
          title: 'Create your account',
          description: 'Register, then verify your email before signing in.',
        ),
        const SizedBox(height: 16),
        TextField(
          controller: _signupFullNameController,
          decoration: const InputDecoration(
            labelText: 'Full name (optional)',
            prefixIcon: Icon(Icons.person_outline_rounded),
          ),
          textCapitalization: TextCapitalization.words,
          textInputAction: TextInputAction.next,
        ),
        const SizedBox(height: 12),
        TextField(
          controller: _signupEmailController,
          decoration: const InputDecoration(
            labelText: 'Email address',
            prefixIcon: Icon(Icons.email_outlined),
          ),
          keyboardType: TextInputType.emailAddress,
          textInputAction: TextInputAction.next,
          autocorrect: false,
        ),
        const SizedBox(height: 12),
        TextField(
          controller: _signupPasswordController,
          decoration: InputDecoration(
            labelText: 'Password',
            prefixIcon: const Icon(Icons.lock_outline_rounded),
            suffixIcon: IconButton(
              onPressed: () {
                setState(
                  () => _signupPasswordVisible = !_signupPasswordVisible,
                );
              },
              icon: Icon(
                _signupPasswordVisible
                    ? Icons.visibility_off_outlined
                    : Icons.visibility_outlined,
              ),
              tooltip: _signupPasswordVisible
                  ? 'Hide password'
                  : 'Show password',
            ),
          ),
          obscureText: !_signupPasswordVisible,
          enableSuggestions: false,
          autocorrect: false,
          textInputAction: TextInputAction.done,
          onSubmitted: (_) {
            if (!_signingUp) {
              _signup();
            }
          },
        ),
        const SizedBox(height: 14),
        SizedBox(
          width: double.infinity,
          child: FilledButton.icon(
            onPressed: _signingUp ? null : _signup,
            icon: _signingUp
                ? const SizedBox(
                    width: 18,
                    height: 18,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Icon(Icons.person_add_alt_1_rounded),
            label: const Text('Create account'),
          ),
        ),
        if (_signupMessage != null) ...[
          const SizedBox(height: 12),
          _AuthFeedback(message: _signupMessage!),
        ],
      ],
    );
  }

  Widget _buildVerifyPanel(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _buildPanelIntro(
          context,
          title: 'Verify your email',
          description: 'Enter the verification token sent after signup.',
        ),
        const SizedBox(height: 16),
        TextField(
          controller: _verificationTokenController,
          decoration: const InputDecoration(
            labelText: 'Verification token',
            prefixIcon: Icon(Icons.verified_user_outlined),
          ),
          autocorrect: false,
          textInputAction: TextInputAction.done,
          onSubmitted: (_) {
            if (!_verifyingEmail) {
              _verifyEmail();
            }
          },
        ),
        const SizedBox(height: 14),
        SizedBox(
          width: double.infinity,
          child: FilledButton.icon(
            onPressed: _verifyingEmail ? null : _verifyEmail,
            icon: _verifyingEmail
                ? const SizedBox(
                    width: 18,
                    height: 18,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Icon(Icons.verified_rounded),
            label: const Text('Verify email'),
          ),
        ),
        if (_verificationMessage != null) ...[
          const SizedBox(height: 12),
          _AuthFeedback(message: _verificationMessage!),
        ],
      ],
    );
  }

  Widget _buildResetPanel(BuildContext context) {
    final theme = Theme.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _buildPanelIntro(
          context,
          title: 'Reset your password',
          description:
              'Use the reset token from your email and choose a new password.',
        ),
        const SizedBox(height: 16),
        TextField(
          controller: _resetTokenController,
          decoration: const InputDecoration(
            labelText: 'Password reset token',
            prefixIcon: Icon(Icons.vpn_key_outlined),
          ),
          autocorrect: false,
          textInputAction: TextInputAction.next,
        ),
        const SizedBox(height: 12),
        TextField(
          controller: _resetPasswordController,
          decoration: InputDecoration(
            labelText: 'New password',
            prefixIcon: const Icon(Icons.lock_reset_rounded),
            suffixIcon: IconButton(
              onPressed: () {
                setState(() => _resetPasswordVisible = !_resetPasswordVisible);
              },
              icon: Icon(
                _resetPasswordVisible
                    ? Icons.visibility_off_outlined
                    : Icons.visibility_outlined,
              ),
              tooltip: _resetPasswordVisible
                  ? 'Hide password'
                  : 'Show password',
            ),
          ),
          obscureText: !_resetPasswordVisible,
          enableSuggestions: false,
          autocorrect: false,
          textInputAction: TextInputAction.done,
          onSubmitted: (_) {
            if (!_resettingPassword) {
              _resetPassword();
            }
          },
        ),
        const SizedBox(height: 14),
        SizedBox(
          width: double.infinity,
          child: FilledButton.icon(
            onPressed: _resettingPassword ? null : _resetPassword,
            icon: _resettingPassword
                ? const SizedBox(
                    width: 18,
                    height: 18,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Icon(Icons.password_rounded),
            label: const Text('Reset password'),
          ),
        ),
        if (_resetPasswordMessage != null) ...[
          const SizedBox(height: 12),
          _AuthFeedback(message: _resetPasswordMessage!),
        ],
        const SizedBox(height: 18),
        Divider(height: 1, color: theme.dividerColor),
        const SizedBox(height: 16),
        Text(
          'Need a reset token?',
          style: theme.textTheme.titleSmall?.copyWith(
            fontWeight: FontWeight.w800,
          ),
        ),
        const SizedBox(height: 4),
        Text(
          'Request password reset instructions for your account email.',
          style: theme.textTheme.bodySmall?.copyWith(
            color: theme.colorScheme.onSurfaceVariant,
          ),
        ),
        const SizedBox(height: 12),
        TextField(
          controller: _forgotEmailController,
          decoration: const InputDecoration(
            labelText: 'Account email',
            prefixIcon: Icon(Icons.email_outlined),
          ),
          keyboardType: TextInputType.emailAddress,
          autocorrect: false,
          textInputAction: TextInputAction.done,
          onSubmitted: (_) {
            if (!_requestingPasswordReset) {
              _forgotPassword();
            }
          },
        ),
        const SizedBox(height: 12),
        SizedBox(
          width: double.infinity,
          child: OutlinedButton.icon(
            onPressed: _requestingPasswordReset ? null : _forgotPassword,
            icon: _requestingPasswordReset
                ? const SizedBox(
                    width: 18,
                    height: 18,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Icon(Icons.mark_email_read_outlined),
            label: const Text('Send reset instructions'),
          ),
        ),
        if (_forgotPasswordMessage != null) ...[
          const SizedBox(height: 12),
          _AuthFeedback(message: _forgotPasswordMessage!),
        ],
      ],
    );
  }

  Widget _buildAdvancedCredentials(BuildContext context) {
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;

    return AppCard(
      padding: EdgeInsets.zero,
      child: ExpansionTile(
        initiallyExpanded: _advancedCredentialsExpanded,
        onExpansionChanged: (expanded) {
          setState(() => _advancedCredentialsExpanded = expanded);
        },
        shape: const Border(),
        collapsedShape: const Border(),
        tilePadding: const EdgeInsets.symmetric(horizontal: 18, vertical: 4),
        childrenPadding: const EdgeInsets.fromLTRB(18, 0, 18, 18),
        leading: Container(
          width: 38,
          height: 38,
          decoration: BoxDecoration(
            color: scheme.surfaceContainerHighest,
            borderRadius: BorderRadius.circular(11),
          ),
          child: Icon(Icons.key_rounded, color: scheme.onSurfaceVariant),
        ),
        title: Text(
          'Advanced Credentials',
          style: theme.textTheme.titleMedium?.copyWith(
            fontWeight: FontWeight.w900,
          ),
        ),
        subtitle: const Text('Manual auth and OpenAI runtime keys'),
        children: [
          Align(
            alignment: Alignment.centerLeft,
            child: Text(
              'Use these fields only when credentials are provided outside the login flow.',
              style: theme.textTheme.bodySmall?.copyWith(
                color: scheme.onSurfaceVariant,
              ),
            ),
          ),
          const SizedBox(height: 14),
          TextField(
            controller: _jwtTokenController,
            decoration: const InputDecoration(
              labelText: 'JWT token',
              prefixIcon: Icon(Icons.password_rounded),
            ),
            obscureText: true,
            enableSuggestions: false,
            autocorrect: false,
            textInputAction: TextInputAction.next,
          ),
          const SizedBox(height: 12),
          TextField(
            controller: _apiKeyController,
            decoration: const InputDecoration(
              labelText: 'Backend API Key (optional / advanced)',
              prefixIcon: Icon(Icons.key_rounded),
            ),
            obscureText: true,
            enableSuggestions: false,
            autocorrect: false,
            textInputAction: TextInputAction.done,
          ),
          const SizedBox(height: 12),
          TextField(
            controller: _openAiApiKeyController,
            decoration: const InputDecoration(
              labelText: 'OpenAI API Key (required for Upload + Chat)',
              prefixIcon: Icon(Icons.auto_awesome_rounded),
            ),
            obscureText: true,
            enableSuggestions: false,
            autocorrect: false,
            textInputAction: TextInputAction.done,
          ),
          const SizedBox(height: 8),
          Align(
            alignment: Alignment.centerLeft,
            child: StatusBadge(
              label: widget.session.hasActiveOpenAiKey
                  ? 'OpenAI Runtime Key Active'
                  : 'OpenAI Runtime Key Missing',
              color: widget.session.hasActiveOpenAiKey
                  ? const Color(0xFF15803D)
                  : const Color(0xFFB45309),
              icon: widget.session.hasActiveOpenAiKey
                  ? Icons.check_circle_rounded
                  : Icons.warning_amber_rounded,
            ),
          ),
          const SizedBox(height: 12),
          TextField(
            controller: _tavilyApiKeyController,
            decoration: const InputDecoration(
              labelText: 'Tavily API Key (optional for Web Search)',
              prefixIcon: Icon(Icons.travel_explore_rounded),
            ),
            obscureText: true,
            enableSuggestions: false,
            autocorrect: false,
            textInputAction: TextInputAction.done,
          ),
          if (_credentialMessage != null) ...[
            const SizedBox(height: 8),
            Align(
              alignment: Alignment.centerLeft,
              child: Text(_credentialMessage!),
            ),
          ],
          const SizedBox(height: 14),
          LayoutBuilder(
            builder: (context, constraints) {
              final saveButton = FilledButton.icon(
                onPressed: _saveAuthCredentials,
                icon: const Icon(Icons.save_rounded),
                label: const Text('Save credentials'),
              );
              final logoutButton = OutlinedButton.icon(
                onPressed: widget.session.jwtToken == null ? null : _logout,
                icon: const Icon(Icons.logout_rounded),
                label: const Text('Logout'),
              );

              if (constraints.maxWidth < 420) {
                return Column(
                  children: [
                    SizedBox(width: double.infinity, child: saveButton),
                    const SizedBox(height: 8),
                    SizedBox(width: double.infinity, child: logoutButton),
                  ],
                );
              }

              return Row(
                children: [
                  Expanded(child: saveButton),
                  const SizedBox(width: 10),
                  Expanded(child: logoutButton),
                ],
              );
            },
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return SafeArea(
      child: ListView(
        keyboardDismissBehavior: ScrollViewKeyboardDismissBehavior.onDrag,
        padding: const EdgeInsets.all(16),
        children: [
          Text(
            'Settings',
            style: Theme.of(
              context,
            ).textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w900),
          ),
          const SizedBox(height: 14),
          _buildAccountSection(context),
          const SizedBox(height: 14),
          _buildAdvancedCredentials(context),
          const SizedBox(height: 14),
          AppCard(
            child: Column(
              children: [
                TextField(
                  controller: _urlController,
                  decoration: const InputDecoration(
                    labelText: 'Backend base URL',
                    prefixIcon: Icon(Icons.link_rounded),
                  ),
                  keyboardType: TextInputType.url,
                ),
                const SizedBox(height: 12),
                FilledButton.icon(
                  onPressed: _checking ? null : _testHealth,
                  icon: _checking
                      ? const SizedBox(
                          width: 18,
                          height: 18,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : const Icon(Icons.health_and_safety_rounded),
                  label: const Text('Save and Test Health'),
                ),
                if (_healthMessage != null) ...[
                  const SizedBox(height: 12),
                  Text(_healthMessage!),
                ],
              ],
            ),
          ),
          const SizedBox(height: 14),
          AppCard(
            child: Column(
              children: [
                DropdownButtonFormField<ThemeMode>(
                  initialValue: widget.session.themeMode,
                  decoration: const InputDecoration(
                    labelText: 'Theme mode',
                    prefixIcon: Icon(Icons.contrast_rounded),
                  ),
                  items: const [
                    DropdownMenuItem(
                      value: ThemeMode.system,
                      child: Text('System'),
                    ),
                    DropdownMenuItem(
                      value: ThemeMode.light,
                      child: Text('Light'),
                    ),
                    DropdownMenuItem(
                      value: ThemeMode.dark,
                      child: Text('Dark'),
                    ),
                  ],
                  onChanged: (value) {
                    if (value != null) {
                      widget.session.setThemeMode(value);
                    }
                  },
                ),
                const SizedBox(height: 12),
                DropdownButtonFormField<String>(
                  initialValue:
                      ApiConstants.supportedEmbeddingProviders.contains(
                        widget.session.embeddingProvider,
                      )
                      ? widget.session.embeddingProvider
                      : ApiConstants.defaultEmbeddingProvider,
                  decoration: const InputDecoration(
                    labelText: 'Embedding provider',
                    prefixIcon: Icon(Icons.memory_rounded),
                  ),
                  items: ApiConstants.supportedEmbeddingProviders
                      .map(
                        (provider) => DropdownMenuItem(
                          value: provider,
                          child: Text(provider),
                        ),
                      )
                      .toList(),
                  onChanged: (value) {
                    if (value != null) {
                      widget.session.setEmbeddingProvider(value);
                    }
                  },
                ),
                const SizedBox(height: 4),
                SwitchListTile(
                  value: widget.session.debugMode,
                  onChanged: widget.session.setDebugMode,
                  title: const Text('Debug API logging'),
                  subtitle: const Text(
                    'Log request URL, body, status, response',
                  ),
                  contentPadding: EdgeInsets.zero,
                ),
              ],
            ),
          ),
          const SizedBox(height: 14),
          AppCard(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const StatusBadge(
                  label: 'Current session',
                  color: Color(0xFF2563EB),
                  icon: Icons.key_rounded,
                ),
                const SizedBox(height: 12),
                Text(
                  'Collection: ${widget.session.collectionName.isEmpty ? "Not set" : widget.session.collectionName}',
                ),
                Text(
                  'Session: ${widget.session.sessionId.isEmpty ? "Not set" : widget.session.sessionId}',
                ),
                const SizedBox(height: 12),
                Wrap(
                  spacing: 10,
                  runSpacing: 10,
                  children: [
                    OutlinedButton.icon(
                      onPressed: widget.session.resetSession,
                      icon: const Icon(Icons.restart_alt_rounded),
                      label: const Text('Reset session'),
                    ),
                    OutlinedButton.icon(
                      onPressed: () async {
                        await widget.session.clearAll();
                        _urlController.text = widget.session.backendUrl;
                        _emailController.clear();
                        _passwordController.clear();
                        _signupFullNameController.clear();
                        _signupEmailController.clear();
                        _signupPasswordController.clear();
                        _verificationTokenController.clear();
                        _forgotEmailController.clear();
                        _resetTokenController.clear();
                        _resetPasswordController.clear();
                        _jwtTokenController.clear();
                        _apiKeyController.clear();
                        _openAiApiKeyController.clear();
                        _tavilyApiKeyController.clear();
                        setState(() {
                          _loginMessage = null;
                          _signupMessage = null;
                          _verificationMessage = null;
                          _forgotPasswordMessage = null;
                          _resetPasswordMessage = null;
                        });
                      },
                      icon: const Icon(Icons.delete_outline_rounded),
                      label: const Text('Clear local settings'),
                    ),
                  ],
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

enum _AccountPanel {
  login('Login', Icons.login_rounded),
  signup('Signup', Icons.person_add_alt_1_rounded),
  verify('Verify', Icons.verified_user_outlined),
  reset('Reset', Icons.lock_reset_rounded);

  const _AccountPanel(this.label, this.icon);

  final String label;
  final IconData icon;
}

class _AuthFeedback extends StatelessWidget {
  const _AuthFeedback({required this.message});

  final String message;

  bool get _isError {
    final value = message.toLowerCase();
    return value.contains('required') ||
        value.contains('failed') ||
        value.contains('error') ||
        value.contains('invalid') ||
        value.contains('not reachable') ||
        value.contains('timed out') ||
        value.contains('status ');
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final title = _isError ? 'Action required' : 'Completed';
    final background = _isError
        ? const Color(0xFFFFF7F7)
        : const Color(0xFFF4FBF7);
    final border = _isError ? const Color(0xFFF4C7C7) : const Color(0xFFC7E8D1);
    final foreground = _isError
        ? const Color(0xFFA93030)
        : const Color(0xFF287A4B);

    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: background,
        border: Border.all(color: border),
        borderRadius: BorderRadius.circular(14),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            width: 32,
            height: 32,
            decoration: BoxDecoration(
              color: foreground.withValues(alpha: .10),
              borderRadius: BorderRadius.circular(9),
            ),
            child: Icon(
              _isError
                  ? Icons.error_outline_rounded
                  : Icons.check_circle_outline_rounded,
              size: 18,
              color: foreground,
            ),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  title,
                  style: theme.textTheme.labelMedium?.copyWith(
                    color: foreground,
                    fontWeight: FontWeight.w900,
                  ),
                ),
                const SizedBox(height: 2),
                Text(
                  message,
                  style: theme.textTheme.bodySmall?.copyWith(
                    color: foreground,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
