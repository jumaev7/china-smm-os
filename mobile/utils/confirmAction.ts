import { Alert } from 'react-native';

import type { OperatorWorkspaceAction } from '@/types/workspace';

/** Generic internal approval — no external channel claim. */
const INTERNAL_APPROVE_CONFIRM =
  'This marks internal approval and starts client review where configured. ' +
  'It does not publish to Facebook, Instagram, or other social media, and does not bypass client approval.';

/**
 * When the action contract sets external_side_effect=true (approve_content),
 * confirmation must state that a Telegram client review preview MAY be sent.
 */
const EXTERNAL_TELEGRAM_APPROVE_CONFIRM =
  'This marks internal approval and may send a review preview or notification ' +
  'to the client via Telegram. It does not publish to Facebook, Instagram, or ' +
  'other social media, and does not bypass client approval.';

const TELEGRAM_EXTERNAL_CLAUSE =
  'Approval may send a review preview or notification to the client via Telegram.';

/**
 * Resolve confirmation body from the action contract.
 * Uses external_side_effect — never category/status inference.
 */
export function resolveConfirmationMessage(
  action: OperatorWorkspaceAction,
): string {
  const backendMsg = action.confirmation_message?.trim() || '';

  if (action.external_side_effect) {
    if (backendMsg && /telegram/i.test(backendMsg)) {
      return backendMsg;
    }
    if (backendMsg) {
      return `${backendMsg} ${TELEGRAM_EXTERNAL_CLAUSE}`;
    }
    if (action.action_id === 'approve_content') {
      return EXTERNAL_TELEGRAM_APPROVE_CONFIRM;
    }
    return `${action.label}: ${TELEGRAM_EXTERNAL_CLAUSE}`;
  }

  // external_side_effect=false — must not claim Telegram delivery.
  if (backendMsg) {
    return backendMsg;
  }
  if (action.action_id === 'approve_content') {
    return INTERNAL_APPROVE_CONFIRM;
  }
  return `Confirm: ${action.label}`;
}

/**
 * Native confirmation dialog when backend requires_confirmation.
 * Returns true only if the user accepts. Cancel → zero HTTP.
 */
export function confirmWorkspaceAction(
  action: OperatorWorkspaceAction,
): Promise<boolean> {
  if (!action.requires_confirmation) {
    return Promise.resolve(true);
  }

  const message = resolveConfirmationMessage(action);

  const title =
    action.confirmation_tier === 'high' || action.destructive
      ? `Confirm ${action.label}`
      : action.label;

  return new Promise((resolve) => {
    Alert.alert(title, message, [
      {
        text: 'Cancel',
        style: 'cancel',
        onPress: () => resolve(false),
      },
      {
        text: action.label,
        style: action.destructive ? 'destructive' : 'default',
        onPress: () => resolve(true),
      },
    ]);
  });
}
