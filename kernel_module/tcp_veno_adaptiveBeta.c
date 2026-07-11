/* TCP Veno - Adaptive Beta variant
 *
 * Original: TCP Veno congestion control (Fu & Liew, 2003)
 * Amendment: Adaptive beta threshold scaling with cwnd.
 *            Targets the lossy channel regime (~11 dB SNR).
 *
 * Only change from stock tcp_veno.c:
 *   In veno_cong_avoid(), the static beta comparison value of 6
 *   is replaced with max(3, cwnd/6), preserving legacy behaviour
 *   for small windows while restoring the ~16.7% RTT tolerance
 *   at modern window sizes.
 */

#include <linux/mm.h>
#include <linux/module.h>
#include <linux/skbuff.h>
#include <linux/inet_diag.h>
#include <net/tcp.h>

#define VENO_MAX_DIFF    2
#define VENO_BETA        6
#define VENO_ALPHA       3
#define VPARAM_SHIFT     1

struct veno {
	u8  doing_veno_now;
	u16 cntrtt;
	u32 minrtt;
	u32 basertt;
	u32 inc;
	u32 diff;
};

static inline void veno_enable(struct sock *sk)
{
	struct veno *veno = inet_csk_ca(sk);
	veno->doing_veno_now = 1;
}

static inline void veno_disable(struct sock *sk)
{
	struct veno *veno = inet_csk_ca(sk);
	veno->doing_veno_now = 0;
}

static void veno_init(struct sock *sk)
{
	struct veno *veno = inet_csk_ca(sk);

	veno->basertt = 0x7fffffff;
	veno->minrtt  = 0;
	veno->inc     = 1;
	veno_enable(sk);
}

static void veno_rtt_calc(struct sock *sk, const struct ack_sample *sample)
{
	struct veno *veno = inet_csk_ca(sk);
	u32 rtt;

	if (sample->rtt_us < 0)
		return;

	rtt = sample->rtt_us;
	if (rtt != 0 && rtt < veno->basertt)
		veno->basertt = rtt;

	veno->minrtt = rtt;
	veno->cntrtt++;
}

static void veno_state(struct sock *sk, u8 ca_state)
{
	if (ca_state == TCP_CA_Open)
		veno_enable(sk);
	else
		veno_disable(sk);
}

static void veno_cwnd_event(struct sock *sk, enum tcp_ca_event event)
{
	if (event == CA_EVENT_CWND_RESTART || event == CA_EVENT_TX_START)
		veno_init(sk);
}

static void veno_cong_avoid(struct sock *sk, u32 ack, u32 acked)
{
	struct tcp_sock *tp = tcp_sk(sk);
	struct veno *veno = inet_csk_ca(sk);
	u32 cwnd, target_cwnd, beta_adaptive;

	if (!veno->doing_veno_now) {
		tcp_reno_cong_avoid(sk, ack, acked);
		return;
	}

	if (veno->cntrtt <= 2) {
		tcp_reno_cong_avoid(sk, ack, acked);
		return;
	}

	if (veno->basertt != 0x7fffffff) {
		cwnd = tcp_snd_cwnd(tp);
		target_cwnd = (u64)cwnd * veno->basertt / veno->minrtt;

		if (cwnd > target_cwnd)
			veno->diff = cwnd - target_cwnd;
		else
			veno->diff = 0;

		/*
		 * AMENDMENT: Adaptive beta.
		 * Replace the static comparison threshold (VENO_BETA = 6)
		 * with an adaptive value that scales with the congestion window.
		 * beta_adaptive = max(3, cwnd/6) << VPARAM_SHIFT
		 * This restores the original ~16.7% RTT tolerance regardless
		 * of window size, preventing threshold collapse at modern speeds.
		 */
		beta_adaptive = max_t(u32, VENO_ALPHA,
				      cwnd / VENO_BETA) << VPARAM_SHIFT;

		if (tcp_in_slow_start(tp)) {
			tcp_slow_start(tp, acked);
		} else {
			if (veno->diff < beta_adaptive) {
				tcp_cong_avoid_ai(tp, cwnd, acked);
			} else {
				if (veno->inc && (tp->snd_cwnd_cnt >= cwnd)) {
					if (tcp_snd_cwnd(tp) < tp->snd_cwnd_clamp)
						tcp_snd_cwnd_set(tp,
							tcp_snd_cwnd(tp) + 1);
					tp->snd_cwnd_cnt = 0;
					veno->inc = 0;
				} else {
					tcp_cong_avoid_ai(tp, cwnd, acked);
					veno->inc = 1;
				}
			}
		}
	} else {
		tcp_reno_cong_avoid(sk, ack, acked);
	}
}

static u32 veno_ssthresh(struct sock *sk)
{
	const struct tcp_sock *tp = tcp_sk(sk);
	const struct veno *veno = inet_csk_ca(sk);

	if (veno->diff < (VENO_BETA << VPARAM_SHIFT))
		return max(tcp_snd_cwnd(tp) * 3 / 4, 2U);
	else
		return max(tcp_snd_cwnd(tp) >> 1U, 2U);
}

static struct tcp_congestion_ops tcp_veno_adaptivebeta __read_mostly = {
	.init        = veno_init,
	.ssthresh    = veno_ssthresh,
	.cong_avoid  = veno_cong_avoid,
	.set_state   = veno_state,
	.cwnd_event  = veno_cwnd_event,
	.pkts_acked  = veno_rtt_calc,
	.owner       = THIS_MODULE,
	.name        = "veno_ab",
};

static int __init veno_ab_register(void)
{
	return tcp_register_cong_control(&tcp_veno_adaptivebeta);
}

static void __exit veno_ab_unregister(void)
{
	tcp_unregister_cong_control(&tcp_veno_adaptivebeta);
}

module_init(veno_ab_register);
module_exit(veno_ab_unregister);

MODULE_AUTHOR("Based on Fu & Liew 2003; Adaptive Beta amendment: L. Friggieri Cordina");
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("TCP Veno - Adaptive Beta amendment");