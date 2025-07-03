class BonificacaoRouter:
    route_app_labels = {'salesapp'}

    def db_for_read(self, model, **hints):
        if model._meta.app_label == 'salesapp' and model.__name__ == 'Bonificacao':
            return 'bonificacao_db'
        return None

    def db_for_write(self, model, **hints):
        if model._meta.app_label == 'salesapp' and model.__name__ == 'Bonificacao':
            return False
        return None

    def allow_relation(self, obj1, obj2, **hints):
        if obj1._state.db == 'bonificacao_db' or obj2._state.db == 'bonificacao_db':
            return obj1._state.db == obj2._state.db
        return None

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        if model_name == 'bonificacao':
            return False
        if db == 'bonificacao_db':
            return False

        return None