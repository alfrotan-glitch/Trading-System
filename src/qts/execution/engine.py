                            "quantity": str(intent.quantity),
                            "side": intent.side.value,
                            "shadow": True,
                        },
                    )
                )
            return self.om.get(intent.client_order_id), []

        # Final local/durable gate immediately before the economic broker call.
        # Earlier risk/kill checks can become stale while a request is being
        # prepared. If another local path cancelled the order, never resurrect
        # it by submitting to the venue.
        current = self.om.get(intent.client_order_id)
        if current is None or current.state is not OrderState.PENDING:
            return current, []
        if self.risk.killed or self._suspended:
            reason = "kill switch active" if self.risk.killed else "execution suspended"
            cancelled = self.om.update_state(
                intent.client_order_id,
                OrderState.CANCELLED,
                reject_reason=reason,
            )
            if self.audit:
                self.audit.emit(
                    DomainEvent(
                        event_type=EventType.NO_TRADE,
                        payload={
                            "client_order_id": intent.client_order_id,
                            "strategy_id": intent.strategy_id,
                            "reason": "FINAL_EXECUTION_GATE",
                            "detail": reason,
                        },
                    )
                )
            return cancelled, []

        try:
            broker_order = self.broker.submit(intent)
            self.om.update_state(
                intent.client_order_id,
                OrderState.ACCEPTED,
                exchange_order_id=broker_order.exchange_order_id or broker_order.order_id,
            )
        except Exception as e:
            # Classify from the exception contract, never from human-readable
            # error text. Broker adapters must raise TimeoutError/ConnectionError
            # (or explicitly mark an exception) when venue outcome is unknown;
            # ordinary ValueError/RuntimeError rejections stay definitive.
            is_ambiguous = isinstance(e, (TimeoutError, ConnectionError)) or bool(
                getattr(e, "ambiguous", False)
            )
            state = OrderState.AMBIGUOUS if is_ambiguous else OrderState.REJECTED
            self.om.update_state(intent.client_order_id, state, reject_reason=str(e))
            if self.audit:
                # Use consistent from/to schema plus error detail (G12)
                # The update_state above already emitted from/to, this is additional error context
                self.audit.emit(
                    DomainEvent(
                        event_type=EventType.ORDER_EVENT,
                        payload={
                            "client_order_id": intent.client_order_id,
                            "from": OrderState.PENDING.value,
                            "to": state.value,
                            "error": str(e),