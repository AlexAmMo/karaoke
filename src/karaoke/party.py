"""User-facing room settings and assignment of performers to a particular turn."""

from __future__ import annotations

from .participants import VoiceNames, physical_inputs
from .songs import SongError


class PartyMixin:
    def input_options(self):
        return {**physical_inputs(self.engine), **self.remote.mics.inputs()}

    def route_profile(self):
        # SDL backends without an identifiable output cannot share a calibration across launches.
        if not self.engine.get("output_device") and not hasattr(self, "_session_route"):
            from uuid import uuid4

            self._session_route = uuid4().hex
        return (
            str(self.engine.get("output_device") or self._session_route)
            + "|"
            + "|".join(
                str(self.engine.get(k, ""))
                for k in (
                    "capture_backend",
                    "audio_driver",
                    "output_device",
                    "output_hz",
                    "output_frames",
                )
            )
        )

    def remember_measurement(self):
        measurement = self.engine.get("calibration") or {}
        if measurement.get("status") != "done" or not self.engine.get("output_device"):
            return
        if measurement == getattr(self, "_last_measurement", None):
            return
        self._last_measurement = measurement
        if measurement.get("output_device") != self.engine["output_device"] or measurement.get(
            "output_hz"
        ) != self.engine.get("output_hz"):
            return
        for key, source in physical_inputs(self.engine).items():
            if all(source.get(k) == measurement.get(k) for k in ("device", "channel", "name")):
                self.store.configure("measurement:" + self.route_profile() + ":" + key, measurement)
                return

    def party_state(self):
        return {
            "singers": self.people.list(),
            "inputs": [{"id": key, "label": v["label"]} for key, v in self.input_options().items()],
        }

    def voice_names(self, choices):
        people = {p["id"]: p for p in self.people.list()}
        if not isinstance(choices, list) or not 1 <= len(choices) <= 10:
            raise SongError("Elige de uno a diez cantantes.")
        inputs = self.input_options()
        for c in choices:
            if not isinstance(c, dict) or not (
                (isinstance(c.get("singer"), str) and c["singer"] in people)
                or (c.get("singer") is None and isinstance(c.get("name"), str))
            ):
                raise SongError("Actualiza los cantantes de este turno.")
            if c.get("input") is not None and (
                not isinstance(c["input"], str) or c["input"] not in inputs
            ):
                raise SongError("La entrada ha cambiado. Elige otra.")
        return VoiceNames(choices, people)

    def party_action(self, action):
        bits = action.split(":")
        op = bits[1]
        if op == "create":
            self.people.create(self.fields.get("new_singer", ""))
            self.fields["new_singer"] = ""
        elif op == "person":
            self.person_detail = bits[2]
            self.page = "Cantante"
        elif op == "retire":
            self.people.retire(self.person_detail)
            self.page = "Cantantes"
        elif op == "default":
            uid = bits[2]
            group = [
                p
                for p in self.store.setting("host_lineup", [])
                if any(x["id"] == p for x in self.people.list())
            ]
            if uid in group:
                group.remove(uid)
            else:
                group.append(uid)
            self.store.configure("host_lineup", group)
        elif op == "input":
            key = ":".join(bits[2:]) or None
            if key and key not in self.input_options():
                raise SongError("La entrada se ha desconectado.")
            self.people.configure(self.person_detail, input_key=key)
            self.page = "Cantante"
        elif op == "calibrate":
            singer = next((p for p in self.people.list() if p["id"] == self.person_detail), {})
            key = singer.get("preferred")
            if key not in self.input_options():
                raise SongError("Asigna primero una entrada conectada.")
            try:
                delay = int(self.fields.get("route_delay", "0"))
                gain = int(self.fields.get("route_gain", "0"))
            except ValueError:
                raise SongError("Introduce valores numéricos.") from None
            if not -500 <= delay <= 500 or not 0 <= gain <= 100:
                raise SongError("Elige entre −500 y 500 ms y un retorno de 0 a 100 %.")
            self.store.configure(
                "route:" + self.route_profile() + ":" + key,
                {"latency_ms": delay, "gain": gain / 100},
            )
            self.fields.pop("route_delay", None)
            self.fields.pop("route_gain", None)
            self.page = "Cantante"
            self.message = "Ajuste guardado para esta entrada y salida."
        elif op == "measure":
            if self.active:
                raise SongError("Mide el retorno entre canciones.")
            person = next(p for p in self.people.list() if p["id"] == self.person_detail)
            source = self.input_options().get(person.get("preferred"), {})
            if "device" not in source:
                raise SongError("Conecta una entrada de audio física.")
            self.command(
                "calibrate", device=source["device"], channel=source["channel"], name=source["name"]
            )
        elif op == "tune":
            self.fields.pop("route_delay", None)
            self.fields.pop("route_gain", None)
            self.page = "Calibrar entrada"
        elif op == "edit":
            self.page = "Voces del turno"
            turn = next((t for t in self.store.queue() if t["id"] == self.turn_detail), None)
            if not turn or turn["state"] != "queued":
                raise SongError("El turno ya no está pendiente.")
            self.edit_voices = self.people.voices(turn)
        elif op == "toggle":
            uid = bits[2]
            if any(v.get("singer") == uid for v in self.edit_voices):
                self.edit_voices = [v for v in self.edit_voices if v.get("singer") != uid]
            else:
                person = next((p for p in self.people.list() if p["id"] == uid), None)
                if person and len(self.edit_voices) < 10:
                    self.edit_voices.append(dict(singer=uid, name=person["name"]))
        elif op == "drop":
            self.edit_voices.pop(int(bits[2]))
        elif op == "choose":
            self.edit_slot = int(bits[2])
            self.page = "Entrada del turno"
        elif op == "override":
            self.edit_voices[self.edit_slot]["input"] = ":".join(bits[2:]) or None
            self.page = "Voces del turno"
        elif op == "save":
            self.voice_names(self.edit_voices)
            self.people.set_voices(self.turn_detail, self.edit_voices)
            self.page = "Turno"
        else:
            raise SongError("Acción de cantante desconocida.")

    def party_view(self, text, button, field):
        if self.page not in (
            "Cantantes",
            "Cantante",
            "Elegir micrófono",
            "Entrada del turno",
            "Calibrar entrada",
            "Voces del turno",
        ):
            return False
        people = self.people.list()
        inputs = self.input_options()
        person = next((p for p in people if p["id"] == getattr(self, "person_detail", None)), {})
        key = person.get("preferred")
        if self.page == "Cantantes":
            if len(people) < 10:
                field("Nombre de un nuevo cantante", "new_singer")
                button("Añadir cantante", "party:create")
            for p in people:
                button(
                    p["name"],
                    "party:person:" + p["id"],
                    inputs.get(p["preferred"], {}).get(
                        "label",
                        "Entrada automática" if not p["preferred"] else "Entrada desconectada",
                    ),
                )
            if not people:
                field("Primer cantante", "player1", "Cantante 1")
                field("Segundo cantante (opcional)", "player2")
            button("Volver a sesión", "page:Ajustes", style="back")
        elif self.page == "Cantante" and person:
            text(
                person["name"],
                inputs.get(key, {}).get(
                    "label", "Entrada automática" if not key else "Entrada desconectada"
                ),
            )
            selected = person["id"] in self.store.setting("host_lineup", [])
            button(
                "Quitar de mis próximos turnos" if selected else "Cantar en mis próximos turnos",
                "party:default:" + person["id"],
            )
            button("Cambiar micrófono", "page:Elegir micrófono")
            if key in inputs:
                button("Calibrar esta entrada", "party:tune")
            button("Retirar de la sesión", "party:retire", style="link")
            button("Volver a cantantes", "page:Cantantes", style="back")
        elif self.page in ("Elegir micrófono", "Entrada del turno"):
            action = "party:input:" if self.page == "Elegir micrófono" else "party:override:"
            button(
                "Automática" if self.page == "Elegir micrófono" else "Preferencia del cantante",
                action,
            )
            for k, v in inputs.items():
                button(v["label"], action + k)
            button(
                "Volver",
                "page:" + ("Cantante" if self.page == "Elegir micrófono" else "Voces del turno"),
                style="back",
            )
        elif self.page == "Calibrar entrada":
            cfg = self.store.setting("route:" + self.route_profile() + ":" + str(key), {})
            text(
                inputs.get(key, {}).get("label", "Entrada desconectada"),
                "Ajuste para la próxima interpretación.",
            )
            if key in inputs and not inputs[key].get("mobile"):
                button(
                    "Medir recorrido con pulsos",
                    "party:measure",
                    "Se oirán pulsos. Acerca el micro al altavoz.",
                )
                measurement = self.engine.get("calibration") or {}
                if not (
                    measurement.get("name") == inputs[key].get("name")
                    and measurement.get("channel") == inputs[key].get("channel")
                    and measurement.get("output_device") == self.engine.get("output_device")
                    and measurement.get("output_hz") == self.engine.get("output_hz")
                ):
                    measurement = self.store.setting(
                        "measurement:" + self.route_profile() + ":" + key, {}
                    )
                if measurement.get("status") == "done":
                    text(
                        f"Recorrido completo · {measurement.get('roundtrip_ms')} ms",
                        "Es una medida de ida y vuelta.",
                    )
                elif measurement.get("message"):
                    text(measurement["message"])
            field(
                "Compensación temporal en ms (−500 a 500)",
                "route_delay",
                str(cfg.get("latency_ms", 0)),
            )
            field("Escuchar mi voz (0 a 100 %)", "route_gain", str(round(100 * cfg.get("gain", 0))))
            button("Guardar ajuste", "party:calibrate")
            button("Volver", "page:Cantante", style="back")
        elif self.page == "Voces del turno":
            for i, v in enumerate(self.edit_voices):
                route = v.get("input") or v.get("preferred")
                button(
                    v["name"],
                    f"party:choose:{i}",
                    inputs.get(route, {}).get("label", "Entrada automática"),
                )
                button("Quitar " + v["name"], f"party:drop:{i}", style="link")
            for p in people:
                if not any(v.get("singer") == p["id"] for v in self.edit_voices):
                    button("Añadir " + p["name"], "party:toggle:" + p["id"], style="link")
            button("Guardar cantantes", "party:save", style="primary")
            button("Volver al turno", "page:Turno", style="back")
        else:
            return False
        return True
